# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）核心服务。

未完成待办 -> VPS IM 私聊本人（vertu-cli im +users / +send-user）。

范围：task_date <= 今天、状态未完成、owner 非空的待办。
形式：每人一条汇总消息（【PDCA 待办汇总】）：按项目分节 + 同类碎片合并
      成组合事项（app/todos/compose.py），散单单列一节，最多 10 件折叠。
频控：同一任务同一天同一轮（morning / afternoon / manual / auto-*）只催一次；
      手动催办（manual）忽略轮次限制（管理员点按钮就是要再催一遍）。
匹配：owner -> `im +users --query`，按 name/display_name/username/login 精确
      匹配，匹配不到就跳过该人并在结果中报告（管理员手工处理）。
幂等：--client-message-id = pdca-todo-remind-{task_id}-{date}-{round}，重试不重复发。
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.todos.compose import compose_tasks
from app.todos.evidence import (
    fetch_report_text,
    has_followup,
    load_vps_user_map,
    report_window_days,
)
from app.todos.projects import (
    auto_close_meeting_projects,
    ensure_projects,
    load_all_projects,
    match_project,
)
from app.todos.sop import PEOPLE, find_mentions, is_noise
from app.vertu.client import run_vertu_sync, run_vertu_sync_json
from app.statuses import is_done as _status_is_done

DONE_STATUSES = {"done", "completed", "complete", "已完成", "完成"}  # 兼容旧引用，见 app/statuses.py

_SELF_USER_ID: Optional[int] = None

_USER_NAME_FIELDS = ("name", "display_name", "username", "login", "employee_name")


def is_done(status: str | None) -> bool:
    """状态是否已完成。"""
    return _status_is_done(status)


def round_label_for_time(hhmm: str) -> str:
    """把调度时间点映射为轮次标签（默认 09:30=上午、16:30=下午）。"""
    mapping = {"09:30": "morning", "16:30": "afternoon"}
    return mapping.get(hhmm.strip(), "auto-" + hhmm.strip().replace(":", ""))


def today_text() -> str:
    """服务器本地日期（与 bridge.today_text 同口径）。"""
    return datetime.now().strftime("%Y-%m-%d")


def list_pending_tasks(today: str) -> list[PdcaTask]:
    """待催待办：到期日 <= 今天、状态未完成、owner 非空。

    Vemory 无截止待办（task_date == meeting_date）有宽限期：会议满
    todo_remind_grace_hours（默认 48h）后才进入催办，对齐 todo-tracker 语义；
    有 deadline 的待办不受宽限影响（task_date != meeting_date）。
    注：deadline 恰好等于会议日期时也会享受宽限，属可接受的近似。
    """
    with Session(get_engine()) as session:
        rows = session.exec(
            select(PdcaTask)
            .where(
                PdcaTask.task_date <= today,
                PdcaTask.owner != "",
            )
            .order_by(PdcaTask.task_date.asc(), PdcaTask.id.asc()),
        ).all()
    pending = [row for row in rows if not is_done(row.status)]
    settings = get_settings()
    grace_days = max(0, int(math.ceil(settings.todo_remind_grace_hours / 24.0)))
    if not grace_days:
        return pending
    cutoff = (datetime.now() - timedelta(days=grace_days)).strftime("%Y-%m-%d")
    return [
        row
        for row in pending
        if not (
            row.source == "vemory"
            and row.meeting_date
            and row.task_date == row.meeting_date
            and row.meeting_date > cutoff
        )
    ]


def _already_reminded_today(row: PdcaTask, round_label: str, today: str) -> bool:
    """同一轮今天是否已经催过（频控）。"""
    if row.last_reminded_round != round_label:
        return False
    if row.last_reminded_at is None:
        return False
    return row.last_reminded_at.strftime("%Y-%m-%d") == today


def _extract_users(payload: dict | list | None) -> list[dict]:
    """容忍 +users 输出形态差异（裸数组或 {"users": [...]} 等）。"""
    if isinstance(payload, dict):
        for key in ("users", "items", "list", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _match_user(owner: str, users: list[dict]) -> Optional[dict]:
    """按姓名精确匹配；无精确时退化为唯一包含匹配，仍不唯一视为未匹配。"""

    def names(user: dict):
        for field in _USER_NAME_FIELDS:
            value = str(user.get(field) or "").strip()
            if value:
                yield value.casefold()

    wanted = owner.strip().casefold()
    if not wanted:
        return None
    exact = [user for user in users if wanted in list(names(user))]
    if exact:
        return exact[0]
    loose = [
        user
        for user in users
        if any(wanted in name or name in wanted for name in names(user))
    ]
    return loose[0] if len(loose) == 1 else None


def resolve_self_user_id() -> Optional[int]:
    """当前登录 IM 身份（im +me）的 user_id；失败返回 None。

    催办机器人以自己的账号发私聊，给"本人"发会被服务端拒绝
    （不能与自己创建私聊），必须跳过。单例缓存。
    """
    global _SELF_USER_ID
    if _SELF_USER_ID is not None:
        return _SELF_USER_ID or None
    payload = run_vertu_sync_json(["im", "+me"], timeout=20.0)
    user = (payload or {}).get("user") if isinstance(payload, dict) else None
    user_id = None
    if isinstance(user, dict):
        for key in ("userId", "user_id", "id"):
            value = user.get(key)
            if isinstance(value, int) and value > 0:
                user_id = value
                break
    _SELF_USER_ID = user_id or 0
    logger.info("待办催办：当前 IM 身份 user_id={}", user_id)
    return user_id


def resolve_im_user(owner: str, cache: dict[str, Optional[dict]]) -> Optional[dict]:
    """owner -> VPS IM 组织成员；结果按 owner 缓存，一轮内不重复查询。"""
    if owner in cache:
        return cache[owner]
    payload = run_vertu_sync_json(
        ["im", "+users", "--query", owner, "--limit", "10"],
        timeout=30.0,
    )
    user = _match_user(owner, _extract_users(payload))
    if user is None:
        # 服务端组织搜索不可用/为空时的兜底：从「我的会话」反查 user_id
        # （direct_key 形如 u:<对方id>:<自己id>，会话名含双方姓名）
        user = _resolve_via_channels(owner)
    if user is None:
        logger.warning("待办催办：负责人「{}」在 VPS IM 组织里匹配不到", owner)
    cache[owner] = user
    return user


_CHANNELS_SCAN: dict = {"ts": 0.0, "map": {}}


def _lookup_cached(name: str, mapping: dict[str, dict]) -> Optional[dict]:
    """精确优先，其次唯一包含匹配（如「冯磊」→「冯磊-1」）。"""
    wanted = name.strip().casefold()
    if wanted in mapping:
        return mapping[wanted]
    loose = [
        user
        for key, user in mapping.items()
        if wanted in key or key in wanted
    ]
    return loose[0] if len(loose) == 1 else None


# 机器人本人（付汪阳）的别名：会话名里出现本人名字时不映射
_SELF_ALIASES = {alias.casefold() for alias in PEOPLE["付汪阳"]["aliases"]}


def _resolve_via_channels(name: str) -> Optional[dict]:
    """从 im +channels 反查 user_id；结果缓存 10 分钟。"""
    import time

    now = time.monotonic()
    cached = _CHANNELS_SCAN["map"]
    if cached and now - float(_CHANNELS_SCAN.get("ts") or 0) < 600:
        return _lookup_cached(name, cached)
    payload = run_vertu_sync_json(["im", "+channels", "--limit", "100"], timeout=25.0)
    channels = []
    if isinstance(payload, dict):
        channels = payload.get("channels") or []
    self_id = str(resolve_self_user_id() or "")
    wanted_cache: dict[str, dict] = {}
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        dk = str(ch.get("direct_key") or "")
        parts = dk.split(":")
        if not (dk.startswith("u:") and len(parts) == 3):
            continue
        a, b = parts[1], parts[2]
        # direct_key 两侧顺序不定（u:对方:自己 或 u:自己:对方），取非己方
        other_id = b if a == self_id else a
        if other_id == self_id or not other_id.isdigit():
            continue
        ch_name = str(ch.get("name") or "")
        for token in ch_name.replace("，", ",").split(","):
            token = token.strip()
            if token and token.casefold() not in _SELF_ALIASES:
                wanted_cache.setdefault(
                    token.casefold(), {"user_id": int(other_id), "name": token}
                )
    _CHANNELS_SCAN["map"] = wanted_cache
    _CHANNELS_SCAN["ts"] = now
    return _lookup_cached(name, wanted_cache)


def send_direct_message(
    user_id: int | str,
    body: str,
    client_message_id: str,
) -> tuple[bool, str, str]:
    """给本人发私聊；返回 (成功, 失败原因, 消息 id)。

    配置 PDCA_TODO_BOT_APP_ID 时走机器人身份（im +bot-send-user），
    否则回退登录账号身份（im +send-user）。
    """
    bot_app_id = get_settings().todo_bot_app_id
    args = ["im"]
    if bot_app_id:
        args += [
            "+bot-send-user",
            "--app-id", bot_app_id,
            "--user-id", str(user_id),
            "--body", body,
            "--client-message-id", client_message_id,
        ]
    else:
        args += [
            "+send-user",
            "--user-id", str(user_id),
            "--body", body,
            "--client-message-id", client_message_id,
        ]
    code, stdout, stderr = run_vertu_sync(args, timeout=30.0)
    if code == 0:
        message_id = ""
        try:
            payload = json.loads(stdout.strip())
            if isinstance(payload, dict):
                msg = payload.get("message") or {}
                message_id = str(
                    payload.get("message_id")
                    or payload.get("id")
                    or (msg.get("id") if isinstance(msg, dict) else "")
                    or ""
                )
        except (json.JSONDecodeError, ValueError):
            message_id = ""
        return True, "", message_id
    return False, (stderr or stdout or "vertu-cli 发送失败")[:200], ""


def build_person_message(
    owner: str,
    tasks: list[PdcaTask],
    today: str,
    entry_url: str,
    has_vemory: bool = False,
    evidence_checked: bool = False,
) -> str:
    """一人一条消息：同类碎片合并为组合事项（compose），最多 10 件折叠；
    无截止标「会议日期」不标逾期。"""
    composed = compose_tasks(tasks)
    shown, folded = _cap_composed(composed)
    greet = f"{owner}，你好：你还有 {len(tasks)} 项待办未完成"
    if len(composed) < len(tasks):
        greet += f"（合并同类后 {len(composed)} 件）"
    greet += "，请及时跟进："
    lines = [
        "【PDCA 待办催办】",
        greet,
        "",
    ]
    for index, item in enumerate(shown, 1):
        suffix = f"（同项 {item['count']} 条）" if item["merged"] else ""
        lines.append(
            f"{index}. [{_task_flag(item['rep'], today)}] {item['title']}{suffix}"
        )
    if folded:
        lines.append(f"……另有 {folded} 件，下轮再列")
    lines += [
        "",
        f"处理入口：{entry_url}",
    ]
    if has_vemory and evidence_checked:
        lines.append(
            "（以上事项已比对日报、未检出明确跟进记录；在 Vemory 更新状态"
            "或日报注明进展，可停止提醒）"
        )
    elif has_vemory:
        lines.append(
            "（日报系统暂不可用，未做跟进比对；在 Vemory 更新状态可停止提醒）"
        )
    else:
        lines.append("（系统自动提醒，完成后无需回复）")
    return "\n".join(lines)


def _mark_reminded(task_ids: list[int], round_label: str, now: datetime) -> None:
    """落库：记录催办时间/轮次并累计次数。"""
    with Session(get_engine()) as session:
        rows = list(
            session.exec(select(PdcaTask).where(PdcaTask.id.in_(task_ids))).all()
        )
        for row in rows:
            row.last_reminded_at = now
            row.last_reminded_round = round_label
            row.remind_count = (row.remind_count or 0) + 1
            row.updated_at = datetime.utcnow()
            session.add(row)
        session.commit()


def _write_outbox(result: dict) -> None:
    """把本轮结果落盘到 data/outbox，供运维排查。"""
    try:
        settings = get_settings()
        outbox = settings.data_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path: Path = outbox / (result["date"] + "_todo_remind.json")
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        result["outbox"] = str(path)
    except Exception as exc:  # noqa: BLE001 — 落盘失败不影响主流程
        logger.warning("待办催办结果落盘失败: {}", exc)


def _project_reminded_today(project: TodoProject, round_label: str, today: str) -> bool:
    if project.last_reminded_round != round_label:
        return False
    if project.last_reminded_at is None:
        return False
    return project.last_reminded_at.strftime("%Y-%m-%d") == today


def build_project_message(
    project: TodoProject,
    owner_name: str,
    tasks: list[PdcaTask],
    today: str,
    entry_url: str,
    evidence_checked: bool,
    open_total: Optional[int] = None,
    done_total: Optional[int] = None,
) -> str:
    """项目卡片消息：项目名/状态/协调/进度 + 按人拆分条目（同类碎片合并，
    最多 10 件折叠）；无截止标「会议日期」不标逾期。"""
    composed = compose_tasks(tasks)
    shown, folded = _cap_composed(composed)
    lines = ["【PDCA 项目待办】" + project.name]
    status_line = "状态：" + project.status
    if project.coordinator:
        status_line += " ｜ 协调：" + project.coordinator
    if open_total is not None:
        done = done_total or 0
        status_line += " ｜ 项目未完成 " + str(open_total) + " 项"
        if done:
            status_line += "（已完成 " + str(done) + " 项）"
    lines.append(status_line)
    greet = owner_name + "，你名下还有 " + str(len(tasks)) + " 项未完成"
    if len(composed) < len(tasks):
        greet += "（合并同类后 " + str(len(composed)) + " 件）"
    greet += "，请及时跟进："
    lines += ["", greet]
    for index, item in enumerate(shown, 1):
        suffix = "（同项 " + str(item["count"]) + " 条）" if item["merged"] else ""
        lines.append(
            f"{index}. [{_task_flag(item['rep'], today)}] {item['title']}{suffix}"
        )
    if folded:
        lines.append("……另有 " + str(folded) + " 件，下轮再列")
    lines += ["", "处理入口：" + entry_url]
    if evidence_checked:
        lines.append(
            "（已比对日报、未检出明确跟进记录；在 Vemory 更新状态"
            "或日报注明进展，可停止提醒）"
        )
    else:
        lines.append("（日报系统暂不可用，未做跟进比对）")
    return "\n".join(lines)


def build_digest_message(
    owner: str,
    sections: list[dict],
    today: str,
    entry_url: str,
    has_vemory: bool = False,
    evidence_checked: bool = False,
) -> str:
    """每人一条汇总消息：按项目分节（┌ 项目名 + 协调/进度），节内同类碎片
    合并，总数上限 DIGEST_MAX_ITEMS 件，超出折叠到下轮。"""
    total_raw = sum(len(s["tasks"]) for s in sections)
    sections_data: list[dict] = []
    total_composed = 0
    for s in sections:
        composed = compose_tasks(s["tasks"])
        sections_data.append({**s, "composed": composed})
        total_composed += len(composed)

    lines = ["【PDCA 待办汇总】"]
    greet = f"{owner}，你还有 {total_raw} 项待办未完成"
    if total_composed < total_raw:
        greet += f"（合并同类后 {total_composed} 件）"
    lines.append(greet + "：")

    budget = DIGEST_MAX_ITEMS
    folded = 0
    counter = 0
    for s in sections_data:
        if budget <= 0:
            folded += len(s["composed"])
            continue
        lines.append("")
        if s["project"] is None:
            lines.append("┌ 散单待办")
        else:
            header = "┌ " + s["project"].name
            extras: list[str] = []
            if s["project"].coordinator:
                extras.append("协调：" + s["project"].coordinator)
            if s["open_total"] is not None:
                extras.append("项目未完成 " + str(s["open_total"]) + " 项")
                done = s["done_total"] or 0
                if done:
                    extras.append("已完成 " + str(done) + " 项")
            if extras:
                header += "（" + " ｜ ".join(extras) + "）"
            lines.append(header)
        for item in s["composed"]:
            if budget <= 0:
                folded += 1
                continue
            budget -= 1
            counter += 1
            suffix = f"（同项 {item['count']} 条）" if item["merged"] else ""
            lines.append(
                f"{counter}. [{_task_flag(item['rep'], today)}] {item['title']}{suffix}"
            )
    lines += ["", "处理入口：" + entry_url]
    if folded:
        lines.append(f"……另有 {folded} 件，下轮再列")
    if has_vemory and evidence_checked:
        lines.append(
            "（以上事项已比对日报、未检出明确跟进记录；在 Vemory 更新状态"
            "或日报注明进展，可停止提醒）"
        )
    elif has_vemory:
        lines.append(
            "（日报系统暂不可用，未做跟进比对；在 Vemory 更新状态可停止提醒）"
        )
    else:
        lines.append("（系统自动提醒，完成后无需回复）")
    return "\n".join(lines)


def build_group_notice(today: str) -> dict:
    """群知会消息：把今天的未完成待办按人汇总成认领清单。

    与私聊催办同口径（到期 <= 今天、未完成、owner 非空、噪声过滤），
    但不做 IM 用户解析、不发私聊、不改库——纯公示文本。
    返回 {"body", "owners", "tasks", "lines"}。
    """
    tasks = list_pending_tasks(today)
    kept = [
        task for task in tasks
        if not (task.source == "vemory" and is_noise(task.title))
    ]
    with Session(get_engine()) as session:
        project_by_key, _ = ensure_projects(session)
        project_by_id = load_all_projects(session)
    per_owner: dict[str, dict] = {}
    for task in kept:
        owner = (task.owner or "").strip()
        if not owner:
            continue
        entry = per_owner.setdefault(owner, {"count": 0, "projects": []})
        entry["count"] += 1
        name: Optional[str] = None
        if task.project_id and task.project_id in project_by_id:
            name = project_by_id[task.project_id].name
        else:
            rule = match_project(task.title)
            if rule and rule["key"] in project_by_key:
                name = rule["name"]
        if name and name not in entry["projects"]:
            entry["projects"].append(name)
    settings = get_settings()
    lines = [
        f"【PDCA 待办认领】{today} ｜ 共 {len(per_owner)} 人 {len(kept)} 项待办",
        "请各自认领以下事项，随后我会一对一私聊跟进：",
        "",
    ]
    for owner in sorted(per_owner, key=lambda o: -per_owner[o]["count"]):
        entry = per_owner[owner]
        projects = entry["projects"][:3]
        project_text = "：" + "、".join(projects) if projects else ""
        if len(entry["projects"]) > 3:
            project_text += " 等"
        lines.append(f"{owner}（{entry['count']} 项）{project_text}")
    lines += [
        "",
        f"处理入口：{settings.workbench_base_url}",
        "（每日 09:00 群内知会认领，09:30 起私聊跟进；回复私聊可更新状态）",
    ]
    return {
        "body": "\n".join(lines),
        "owners": len(per_owner),
        "tasks": len(kept),
        "lines": lines,
    }


def send_group_notice(today: str, dry_run: bool = False) -> dict:
    """把群知会发到工作大群（专家智能体/账号通道），不落库不改状态。"""
    settings = get_settings()
    channel_id = settings.todo_group_channel_id
    notice = build_group_notice(today)
    if not channel_id:
        return {**notice, "sent": False, "reason": "未配置 PDCA_TODO_GROUP_CHANNEL_ID"}
    if dry_run:
        return {**notice, "sent": False, "dry_run": True, "channel_id": channel_id}
    client_id = "pdca-group-notice-" + today
    agent_slug = os.environ.get("VERTU_AGENT_SLUG", "").strip()
    if agent_slug:
        code, stdout, stderr = run_vertu_sync(
            [
                "im", "+agent-notify",
                "--agent-slug", agent_slug,
                "--channel-id", channel_id,
                "--body", notice["body"],
                "--bot-name", "PDCA待办助手",
                "--event-id", client_id,
            ],
            timeout=30.0,
        )
    else:
        code, stdout, stderr = run_vertu_sync(
            [
                "im", "+send",
                "--channel-id", channel_id,
                "--body", notice["body"],
                "--client-message-id", client_id,
            ],
            timeout=30.0,
        )
    if code != 0:
        return {**notice, "sent": False, "reason": (stderr or stdout or "发送失败")[:200]}
    return {**notice, "sent": True, "channel_id": channel_id, "via": "agent" if agent_slug else "account"}


def _record_sends(
    session: Session,
    records: list[tuple],
    rows: list[PdcaTask],
    round_label: str,
    project_id: Optional[int] = None,
) -> None:
    """落库催办发送记录（人 + message_id + 消息内任务顺序），供回复映射。"""
    from app.models.im_replies import ImRemindSend

    for person, message_id in records:
        session.add(
            ImRemindSend(
                person=person,
                sent_at=datetime.utcnow(),
                message_id=message_id or "",
                item_task_ids=json.dumps(
                    [t.id for t in rows if t.id], ensure_ascii=False
                ),
                project_id=project_id,
                round=round_label,
            )
        )


def _task_flag(task: PdcaTask, today: str) -> str:
    """条目前缀：有截止且逾期 → 逾期；无截止（task_date==meeting_date）→ 会议日期；
    今天到期 → 今日。"""
    if task.task_date == today:
        return "今日"
    if task.source == "vemory" and task.meeting_date and task.task_date == task.meeting_date:
        return "会议 " + task.meeting_date
    if task.task_date < today:
        return "逾期 " + task.task_date
    return task.task_date


MAX_MESSAGE_ITEMS = 10
DIGEST_MAX_ITEMS = 15  # 汇总消息的单条上限（按项目分节，略宽于单项目消息）


def _cap_tasks(tasks: list[PdcaTask]) -> tuple[list[PdcaTask], int]:
    """消息最多列 MAX_MESSAGE_ITEMS 条，其余折叠计数。"""
    if len(tasks) <= MAX_MESSAGE_ITEMS:
        return tasks, 0
    return tasks[:MAX_MESSAGE_ITEMS], len(tasks) - MAX_MESSAGE_ITEMS


def _cap_composed(composed: list[dict]) -> tuple[list[dict], int]:
    """组合事项最多列 MAX_MESSAGE_ITEMS 件，其余折叠计数。"""
    if len(composed) <= MAX_MESSAGE_ITEMS:
        return composed, 0
    return composed[:MAX_MESSAGE_ITEMS], len(composed) - MAX_MESSAGE_ITEMS


def _group_by_owner(items: list[PdcaTask]) -> dict[str, list[PdcaTask]]:
    grouped: dict[str, list[PdcaTask]] = defaultdict(list)
    for item in items:
        grouped[item.owner.strip()].append(item)
    return grouped


def _mark_reminded_rows(
    session: Session,
    rows: list[PdcaTask],
    project: TodoProject | None,
    round_label: str,
    now: datetime,
) -> None:
    for row in rows:
        row.last_reminded_at = now
        row.last_reminded_round = round_label
        row.remind_count = (row.remind_count or 0) + 1
        row.updated_at = datetime.utcnow()
        session.add(row)
    if project is not None:
        project.last_reminded_at = now
        project.last_reminded_round = round_label
        project.remind_count = (project.remind_count or 0) + 1
        project.updated_at = datetime.utcnow()
        session.add(project)


def run_todo_reminders(
    today: str | None = None,
    round_label: str = "manual",
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """执行一轮待办催办。

    @param today 目标日期（默认服务器今天）
    @param round_label 轮次标签（morning/afternoon/manual/auto-*）
    @param force True 时忽略当日轮次频控（手动催办）
    @param dry_run True 时只解析候选人、不发消息、不改库
    @returns 结果摘要（candidates/sent/skipped_owners/failed/summary）
    """
    today = today or today_text()
    now = datetime.now()
    tasks = list_pending_tasks(today)

    # 噪声过滤：会议杂事（纯沟通类且无实质内容）不进催办，保留在库
    noise_skipped: list[dict] = []
    kept_tasks: list[PdcaTask] = []
    for task in tasks:
        if task.source == "vemory" and is_noise(task.title):
            noise_skipped.append({"owner": task.owner, "title": task.title})
        else:
            kept_tasks.append(task)
    tasks = kept_tasks

    entry_url = get_settings().workbench_base_url
    sent: list[dict] = []
    skipped_owners: list[dict] = []
    failed: list[dict] = []
    evidence_skipped: list[dict] = []
    evidence_unavailable: list[dict] = []
    user_cache: dict[str, Optional[dict]] = {}

    vps_map = load_vps_user_map()
    report_cache: dict[int, Optional[str]] = {}
    report_start, report_end = report_window_days(today)

    skip_owners = {
        name.strip()
        for name in get_settings().todo_remind_skip_owners
        if name.strip()
    }
    # 机器人通道：机器人可以给任何人（含机器人属主）发私聊，无需跳过本人；
    # 登录账号通道：不能与自己创建私聊，需要跳过本人。
    bot_mode = bool(get_settings().todo_bot_app_id)
    self_user_id = None if bot_mode else resolve_self_user_id()

    # ── 拆分：项目内待办 vs 项目外个人待办 ──────────────────────────────
    # 注意：commit 会过期 ORM 对象（expire_on_commit），因此 commit 后必须
    # 重新 select 一把再关闭 session，否则后面的 project_by_key/project_by_id
    # 访问会触发 DetachedInstanceError。
    with Session(get_engine()) as session:
        project_by_key, _ = ensure_projects(session)
        auto_close_meeting_projects(session)
        session.commit()
        project_by_id = load_all_projects(session)
        project_by_key = {row.key: row for row in project_by_id.values()}
    project_tasks: dict[int, list[PdcaTask]] = defaultdict(list)
    solo_candidates: list[PdcaTask] = []
    for task in tasks:
        # 行上已有项目归属（关键词/会议/手动）优先，标题关键词匹配兜底
        pid = task.project_id
        if pid and pid in project_by_id:
            project_tasks[pid].append(task)
            continue
        rule = match_project(task.title)
        if rule and rule["key"] in project_by_key:
            project_tasks[project_by_key[rule["key"]].id].append(task)
        elif force or not _already_reminded_today(task, round_label, today):
            solo_candidates.append(task)

    # 项目进度统计（消息内展示：未完成/已完成）
    stats_total: dict[int, int] = {}
    stats_open: dict[int, int] = {}
    if project_tasks:
        with Session(get_engine()) as session:
            project_rows = list(
                session.exec(
                    select(PdcaTask).where(PdcaTask.project_id.in_(list(project_tasks)))
                ).all()
            )
        for row in project_rows:
            stats_total[row.project_id] = stats_total.get(row.project_id, 0) + 1
            if not is_done(row.status):
                stats_open[row.project_id] = stats_open.get(row.project_id, 0) + 1

    def _resolve_and_check(name: str) -> tuple[Optional[int], str]:
        """返回 (user_id, 跳过原因)；user_id 为 None 表示该人不发。"""
        if name in skip_owners:
            return None, "owner_excluded"
        user = resolve_im_user(name, user_cache)
        if user is None:
            return None, "im_user_not_found"
        user_id = user.get("user_id") or user.get("id")
        if not user_id:
            return None, "im_user_missing_id"
        if not bot_mode and user_id == self_user_id:
            return None, "im_self"
        return user_id, ""

    def _filter_evidence(owner: str, items: list[PdcaTask]) -> tuple[list[PdcaTask], bool]:
        """按 owner 的日报过滤 vemory 待办；返回 (保留项, 是否做过比对)。"""
        keep: list[PdcaTask] = []
        checked = False
        vemory_items = [t for t in items if t.source == "vemory"]
        if vemory_items:
            vps_id = vps_map.get(owner)
            report = (
                fetch_report_text(vps_id, report_start, report_end, report_cache)
                if vps_id
                else None
            )
            if report is None:
                evidence_unavailable.append({"owner": owner, "tasks": len(vemory_items)})
                keep += vemory_items
            else:
                checked = True
                for t in vemory_items:
                    if has_followup(t.title, report):
                        evidence_skipped.append({"owner": owner, "title": t.title})
                    else:
                        keep.append(t)
        keep += [t for t in items if t.source != "vemory"]
        return keep, checked

    # 点名指派的任务按被点名人单独分组，不随项目执行人走
    routed: dict[str, list[PdcaTask]] = defaultdict(list)

    # ── 收集：每人名下的待办按项目分节（每人最后只收一条汇总消息） ──
    person_sections: dict[str, list[dict]] = defaultdict(list)
    evidence_by_owner: dict[str, bool] = defaultdict(bool)

    for project_id, owned in sorted(project_tasks.items(), key=lambda kv: project_by_id[kv[0]].name):
        project = project_by_id[project_id]
        if project.status == "已闭环":
            # 项目下又出现未完成待办（如 Vemory 重开任务）→ 会议项目自动重开
            if not dry_run and project.kind == "meeting":
                with Session(get_engine()) as session:
                    proj_row = session.get(TodoProject, project_id)
                    if proj_row is not None and proj_row.status == "已闭环":
                        proj_row.status = "跟进中"
                        proj_row.updated_at = datetime.utcnow()
                        session.add(proj_row)
                        session.commit()
                project.status = "跟进中"
            else:
                continue
        # 点名指派优先：标题里点谁，就挂到谁名下（项目节内不再重复）
        project_owned: list[PdcaTask] = []
        for task in owned:
            # 本轮已催过的行不再进汇总（频控）
            if not force and _already_reminded_today(task, round_label, today):
                continue
            mentioned = find_mentions(task.title)
            # 手工锁定（owner_locked）的条目按指定人走，不再按标题点名重路由
            if mentioned and not getattr(task, "owner_locked", False):
                if force or not _already_reminded_today(task, round_label, today):
                    # 输出 IM 规范名（如 Lina → DEHDAHOUMAIMA），避免错发同名同事
                    person = PEOPLE[mentioned[0]].get("im_name") or mentioned[0]
                    routed[person].append(task)
                else:
                    project_owned.append(task)
            else:
                project_owned.append(task)
        if not project_owned:
            continue
        # 证据按子待办各自的 owner 过滤（项目内多人，各自对各自日报）
        kept: list[PdcaTask] = []
        for owner_name, items in _group_by_owner(project_owned).items():
            k, checked = _filter_evidence(owner_name, items)
            kept += k
            evidence_by_owner[owner_name] = evidence_by_owner[owner_name] or checked
        if not kept:
            continue
        for owner_name, items in sorted(_group_by_owner(kept).items(), key=lambda kv: kv[0]):
            person_sections[owner_name].append(
                {
                    "project": project,
                    "tasks": items,
                    "open_total": stats_open.get(project.id),
                    "done_total": stats_total.get(project.id, 0)
                    - stats_open.get(project.id, 0),
                }
            )

    # 散单 + 点名交办：不挂项目，作为「散单待办」节
    solo_by_owner: dict[str, list[PdcaTask]] = defaultdict(list)
    for task in solo_candidates:
        if force or not _already_reminded_today(task, round_label, today):
            solo_by_owner[task.owner.strip()].append(task)
    for person, items in routed.items():
        solo_by_owner[person].extend(items)
    for owner, owned in solo_by_owner.items():
        keep, checked = _filter_evidence(owner, owned)
        evidence_by_owner[owner] = evidence_by_owner[owner] or checked
        if keep:
            person_sections[owner].append(
                {"project": None, "tasks": keep, "open_total": None, "done_total": None}
            )

    # ── 发送：每人一条汇总消息（按项目分节 + 同类合并） ────────────────
    for owner in sorted(person_sections, key=str.casefold):
        sections = person_sections[owner]
        user_id, reason = _resolve_and_check(owner)
        if user_id is None:
            skipped_owners.append(
                {
                    "owner": owner,
                    "reason": reason,
                    "tasks": sum(len(s["tasks"]) for s in sections),
                }
            )
            continue
        has_vemory = any(
            task.source == "vemory" for s in sections for task in s["tasks"]
        )
        body = build_digest_message(
            owner,
            sections,
            today,
            entry_url,
            has_vemory=has_vemory,
            evidence_checked=evidence_by_owner.get(owner, False),
        )
        all_tasks = [task for s in sections for task in s["tasks"]]
        project_names = [s["project"].name for s in sections if s["project"]]
        solo_included = any(s["project"] is None for s in sections)
        if len(project_names) == 1 and not solo_included:
            group_label = project_names[0]
        elif project_names:
            group_label = "汇总 " + str(len(project_names)) + " 个项目"
        else:
            group_label = ""
        entry = {
            "owner": owner,
            "user_id": user_id,
            "tasks": len(all_tasks),
            "titles": [task.title for task in all_tasks],
            "projects": project_names,
            "project": group_label,
            "digest": True,
        }
        if dry_run:
            entry["preview"] = body
            entry["dry_run"] = True
            sent.append(entry)
            continue
        client_id = "pdca-todo-digest-" + owner + "-" + today + "-" + round_label
        ok, err, message_id = send_direct_message(user_id, body, client_id)
        if not ok:
            failed.append({"owner": owner, "reason": err, "tasks": len(all_tasks)})
            continue
        with Session(get_engine()) as session:
            rows = list(
                session.exec(
                    select(PdcaTask).where(
                        PdcaTask.id.in_([task.id for task in all_tasks if task.id])
                    )
                ).all()
            )
            _mark_reminded_rows(session, rows, None, round_label, now)
            for proj_id in {s["project"].id for s in sections if s["project"]}:
                proj_row = session.get(TodoProject, proj_id)
                if proj_row is not None:
                    _mark_reminded_rows(session, [], proj_row, round_label, now)
            _record_sends(session, [(owner, message_id)], rows, round_label, None)
            session.commit()
        sent.append(entry)

    result = {
        "date": today,
        "round": round_label,
        "dry_run": dry_run,
        "pending_tasks": len(tasks),
        "candidates": len(solo_candidates)
        + sum(len(v) for v in project_tasks.values()),
        "project_entries": len(
            [s for s in sent if s.get("projects")]
        ),
        "person_entries": len(
            [s for s in sent if not s.get("projects")]
        ),
        "sent": sent,
        "skipped_owners": skipped_owners,
        "evidence_skipped": evidence_skipped,
        "evidence_unavailable": evidence_unavailable,
        "noise_skipped": noise_skipped,
        "failed": failed,
        "summary": (
            "待办 " + str(len(tasks)) + " 项，本轮催办 " + str(len(sent)) + " 条消息（汇总）"
            " / 跳过 " + str(len(skipped_owners)) + " 人 / 证据暂缓 "
            + str(len(evidence_skipped)) + " 项 / 证据不可用 "
            + str(len(evidence_unavailable)) + " 人 / 失败 " + str(len(failed)) + " 人"
        ),
    }
    # 只有真实发送才落 outbox；dry-run 预演不得覆盖真实发送记录
    if not dry_run:
        _write_outbox(result)
    return result
