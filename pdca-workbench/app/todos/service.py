# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）核心服务。

未完成待办 -> VPS IM 私聊本人（vertu-cli im +users / +send-user）。

范围：task_date <= 今天、状态未完成、owner 非空的待办。
频控：同一任务同一天同一轮（morning / afternoon / manual / auto-*）只催一次；
      手动催办（manual）忽略轮次限制（管理员点按钮就是要再催一遍）。
匹配：owner -> `im +users --query`，按 name/display_name/username/login 精确
      匹配，匹配不到就跳过该人并在结果中报告（管理员手工处理）。
幂等：--client-message-id = pdca-todo-remind-{task_id}-{date}-{round}，重试不重复发。
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.todos.evidence import (
    fetch_report_text,
    has_followup,
    load_vps_user_map,
    report_window_days,
)
from app.vertu.client import run_vertu_sync, run_vertu_sync_json

DONE_STATUSES = {"done", "completed", "complete", "已完成", "完成"}

_USER_NAME_FIELDS = ("name", "display_name", "username", "login", "employee_name")


def is_done(status: str | None) -> bool:
    """状态是否已完成。"""
    return str(status or "").strip().casefold() in DONE_STATUSES


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
        logger.warning("待办催办：负责人「{}」在 VPS IM 组织里匹配不到", owner)
    cache[owner] = user
    return user


def send_direct_message(
    user_id: int | str,
    body: str,
    client_message_id: str,
) -> tuple[bool, str]:
    """给本人发私聊（im +send-user）；返回 (成功, 失败原因)。"""
    code, stdout, stderr = run_vertu_sync(
        [
            "im", "+send-user",
            "--user-id", str(user_id),
            "--body", body,
            "--client-message-id", client_message_id,
        ],
        timeout=30.0,
    )
    if code == 0:
        return True, ""
    return False, (stderr or stdout or "vertu-cli 发送失败")[:200]


def build_person_message(
    owner: str,
    tasks: list[PdcaTask],
    today: str,
    entry_url: str,
    has_vemory: bool = False,
    evidence_checked: bool = False,
) -> str:
    """一人一条消息，列出其全部待催任务（逾期标日期、今日标今日）。"""
    lines = [
        "【PDCA 待办催办】",
        f"{owner}，你好：你还有 {len(tasks)} 项待办未完成，请及时跟进：",
        "",
    ]
    for index, task in enumerate(tasks, 1):
        flag = f"逾期 {task.task_date}" if task.task_date < today else "今日"
        lines.append(f"{index}. [{flag}] {task.title}")
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
    candidates = [
        task
        for task in tasks
        if force or not _already_reminded_today(task, round_label, today)
    ]

    by_owner: dict[str, list[PdcaTask]] = defaultdict(list)
    for task in candidates:
        by_owner[task.owner.strip()].append(task)

    entry_url = get_settings().workbench_base_url
    sent: list[dict] = []
    skipped_owners: list[dict] = []
    failed: list[dict] = []
    evidence_skipped: list[dict] = []
    evidence_unavailable: list[dict] = []
    user_cache: dict[str, Optional[dict]] = {}

    # 日报证据抑制（仅 Vemory 待办）：有跟进证据的不催。日报源不可用时
    # 不抑制、照常催（fail-open），并如实标注"未做跟进比对"——避免
    # 日报接口故障把催办整体变成静默不发。
    vps_map = load_vps_user_map()
    report_cache: dict[int, Optional[str]] = {}
    report_start, report_end = report_window_days(today)

    for owner in sorted(by_owner, key=str.casefold):
        owned = by_owner[owner]
        keep: list[PdcaTask] = []
        evidence_checked = False
        vemory_tasks = [task for task in owned if task.source == "vemory"]
        if vemory_tasks:
            vps_id = vps_map.get(owner)
            report = (
                fetch_report_text(vps_id, report_start, report_end, report_cache)
                if vps_id
                else None
            )
            if report is None:
                evidence_unavailable.append(
                    {"owner": owner, "tasks": len(vemory_tasks)}
                )
                keep += vemory_tasks
            else:
                evidence_checked = True
                for task in vemory_tasks:
                    if has_followup(task.title, report):
                        evidence_skipped.append(
                            {"owner": owner, "title": task.title}
                        )
                    else:
                        keep.append(task)
        keep += [task for task in owned if task.source != "vemory"]
        if not keep:
            continue
        owned = keep
        user = resolve_im_user(owner, user_cache)
        if user is None:
            skipped_owners.append(
                {"owner": owner, "reason": "im_user_not_found", "tasks": len(owned)}
            )
            continue
        user_id = user.get("user_id") or user.get("id")
        if not user_id:
            skipped_owners.append(
                {"owner": owner, "reason": "im_user_missing_id", "tasks": len(owned)}
            )
            continue
        has_vemory = any(task.source == "vemory" for task in owned)
        body = build_person_message(
            owner,
            owned,
            today,
            entry_url,
            has_vemory=has_vemory,
            evidence_checked=evidence_checked,
        )
        if dry_run:
            sent.append(
                {
                    "owner": owner,
                    "user_id": user_id,
                    "tasks": len(owned),
                    "titles": [task.title for task in owned],
                    "preview": body,
                    "dry_run": True,
                }
            )
            continue
        client_id = (
            "pdca-todo-remind-" + str(min(task.id or 0 for task in owned))
            + "-" + today + "-" + round_label
        )
        ok, err = send_direct_message(user_id, body, client_id)
        if not ok:
            failed.append(
                {"owner": owner, "reason": err, "tasks": len(owned)}
            )
            continue
        _mark_reminded([task.id for task in owned if task.id], round_label, now)
        sent.append(
            {
                "owner": owner,
                "user_id": user_id,
                "tasks": len(owned),
                "titles": [task.title for task in owned],
            }
        )

    result = {
        "date": today,
        "round": round_label,
        "dry_run": dry_run,
        "pending_tasks": len(tasks),
        "candidates": len(candidates),
        "sent": sent,
        "skipped_owners": skipped_owners,
        "evidence_skipped": evidence_skipped,
        "evidence_unavailable": evidence_unavailable,
        "failed": failed,
        "summary": (
            "待办 " + str(len(tasks)) + " 项，本轮催办 " + str(len(sent)) + " 人"
            " / 跳过 " + str(len(skipped_owners)) + " 人 / 证据暂缓 "
            + str(len(evidence_skipped)) + " 项 / 证据不可用 "
            + str(len(evidence_unavailable)) + " 人 / 失败 " + str(len(failed)) + " 人"
        ),
    }
    _write_outbox(result)
    return result
