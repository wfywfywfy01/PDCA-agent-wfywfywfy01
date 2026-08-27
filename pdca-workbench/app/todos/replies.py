# -*- coding: utf-8 -*-
"""IM 回复采集：把催办消息的回复变成待办状态变更。

口径（业务确认 2026-08-27）：
- 明确信号自动生效：「第N条完成」「1和3完成」「全部完成」→ 标记 done，
  项目内全部完成 → 项目转「待验收」；
- 推进中 → 项目转「跟进中」；阻塞 → 项目转「阻塞」并通知协调人；
- 含糊回复（如「有一条已完成」不指明序号）→ 进人工队列（todo_replies unreviewed）；
- 归属：引用/回复我们消息（parent/quote 匹配 message_id）最优先，
  否则按「催办后 48h 内该人私聊新消息」兜底到最近一次发送。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.database import get_engine
from app.models.im_replies import ImRemindSend, TodoReply
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.vertu.client import run_vertu_sync_json

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_DONE_WORDS = ["完成", "搞定", "办完", "做完", "处理完", "done", "finished", "closed", "close"]
_PROGRESS_WORDS = ["推进中", "进行中", "在处理", "跟进中", "在推进", "推进了", "in progress", "working on"]
_BLOCKER_WORDS = ["阻塞", "卡住", "卡了", "推进不了", "需要支持", "需要帮忙", "帮忙协调", "协助"]

_ITEM_RE = re.compile(r"第\s*([0-9]+|[一二两三四五六七八九十]+)\s*(?:条|项|个|点)")
_NUM_RE = re.compile(r"(?<!第)([1-9][0-9]?)\s*(?:条|项|个|点)")
_SEQ_RE = re.compile(r"([1-9][0-9]?)\s*[和、，,]\s*([1-9][0-9]?)")
_ALL_RE = re.compile(r"(全部|所有|都|all)")


def parse_reply(text: str) -> dict:
    """解析回复 → {signal, items, explicit}。

    items: 明确指向的序号列表（1-based，来自催办消息的编号清单）；
           explicit=True 表示指明了序号或「全部」。
    """
    lowered = text.lower()
    signal = ""
    if any(w in text or w in lowered for w in _DONE_WORDS):
        signal = "done"
    elif any(w in text or w in lowered for w in _BLOCKER_WORDS):
        signal = "blocker"
    elif any(w in text or w in lowered for w in _PROGRESS_WORDS):
        signal = "progress"

    items: list = []
    explicit = False
    if _ALL_RE.search(text):
        explicit = True
        items = ["all"]
    else:
        for m in _ITEM_RE.finditer(text):
            raw = m.group(1)
            items.append(int(raw) if raw.isdigit() else _CN_NUM.get(raw, 0))
        for m in _NUM_RE.finditer(text):
            items.append(int(m.group(1)))
        for m in _SEQ_RE.finditer(text):
            items.append(int(m.group(1)))
            items.append(int(m.group(2)))
        items = [i for i in items if i]
        if items:
            explicit = True
    return {"signal": signal, "items": items, "explicit": explicit}


def _channel_for_user(user_id: int) -> Optional[str]:
    payload = run_vertu_sync_json(["im", "+chat", "--user-id", str(user_id)], timeout=20.0)
    if not isinstance(payload, dict):
        return None
    channel = payload.get("channel") or {}
    return str(channel.get("id") or payload.get("channel_id") or "").strip() or None


def _history_since(channel_id: str, since_iso: str, limit: int = 50) -> list[dict]:
    payload = run_vertu_sync_json(
        ["im", "+history", "--channel-id", channel_id, "--date-from", since_iso, "--limit", str(limit)],
        timeout=25.0,
    )
    if not isinstance(payload, dict):
        return []
    return [m for m in (payload.get("messages") or []) if isinstance(m, dict)]


def _apply_done(session: Session, send: ImRemindSend, items: list, reply: TodoReply, text: str, now: datetime) -> bool:
    """按序号把任务标完成；「all」或空 → 全部。返回是否生效。"""
    task_ids = json.loads(send.item_task_ids or "[]")
    targets: list[int] = []
    if not items or items == ["all"]:
        targets = [int(t) for t in task_ids]
    else:
        for idx in items:
            if 1 <= idx <= len(task_ids):
                targets.append(int(task_ids[idx - 1]))
    targets = list(dict.fromkeys(targets))
    if not targets:
        return False
    rows = list(session.exec(select(PdcaTask).where(PdcaTask.id.in_(targets))).all())
    for row in rows:
        row.status = "done"
        row.reply_text = text[:1024]
        row.replied_at = now
        session.add(row)
    reply.status = "applied"
    reply.target_task_id = rows[0].id if len(rows) == 1 else None
    # 项目内全部完成 → 待验收
    for row in rows:
        if row.project_id:
            project = session.get(TodoProject, row.project_id)
            if project:
                remaining = session.exec(
                    select(PdcaTask).where(
                        PdcaTask.project_id == project.id,
                        PdcaTask.status != "done",
                    )
                ).all()
                if not remaining and project.status != "已闭环":
                    project.status = "待验收"
                    project.reply_text = text[:1024]
                    project.replied_at = now
                    session.add(project)
                    reply.target_project_id = project.id
    session.add(reply)
    return True


def poll_replies(hours_back: int = 48) -> dict:
    """轮询回复：对 48h 内发过催办的人查私聊新消息并应用状态变更。"""
    now = datetime.now()
    since = now - timedelta(hours=hours_back)
    result = {"scanned_people": 0, "replies_found": 0, "applied": 0, "queued": 0, "errors": []}

    with Session(get_engine()) as session:
        sends = list(
            session.exec(
                select(ImRemindSend).where(ImRemindSend.sent_at >= since)
            ).all()
        )
        if not sends:
            return result
        by_person: dict[str, list[ImRemindSend]] = {}
        for s in sends:
            by_person.setdefault(s.person, []).append(s)

        from app.todos.service import resolve_im_user

        user_cache: dict[str, Optional[dict]] = {}
        for person, person_sends in by_person.items():
            im_user = resolve_im_user(person, user_cache)
            if im_user is None:
                continue
            vps_id = im_user.get("user_id") or im_user.get("id")
            if not vps_id:
                continue
            result["scanned_people"] += 1
            try:
                channel_id = _channel_for_user(vps_id)
                if not channel_id:
                    continue
                last_send = max(person_sends, key=lambda s: s.sent_at)
                since_iso = last_send.sent_at.strftime("%Y-%m-%dT%H:%M:%S")
                messages = _history_since(channel_id, since_iso)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{person}: {exc}")
                continue
            for msg in messages:
                body = str(msg.get("body") or "").strip()
                if not body or body.startswith("【PDCA"):
                    continue  # 我们自己的消息
                created = msg.get("created_at") or ""
                try:
                    created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    created_dt = now
                if created_dt < last_send.sent_at - timedelta(minutes=2):
                    continue
                parsed = parse_reply(body)
                if not parsed["signal"]:
                    continue
                result["replies_found"] += 1
                reply = TodoReply(
                    person=person,
                    text=body[:1024],
                    at=created_dt,
                    signal=parsed["signal"],
                )
                # 归属：引用/回复匹配优先，否则该人最近一次发送
                parent = str(msg.get("parent_message_id") or msg.get("quote_message_id") or "")
                target_send = next(
                    (s for s in person_sends if s.message_id and s.message_id == parent),
                    None,
                )
                if target_send is None:
                    target_send = last_send
                session.add(reply)
                if parsed["signal"] == "done":
                    if parsed["explicit"]:
                        if _apply_done(session, target_send, parsed["items"], reply, body, now):
                            result["applied"] += 1
                        else:
                            result["queued"] += 1
                    else:
                        result["queued"] += 1  # 未指明序号 → 人工队列
                elif parsed["signal"] == "progress":
                    if target_send.project_id:
                        project = session.get(TodoProject, target_send.project_id)
                        if project and project.status not in ("已闭环", "待验收"):
                            project.status = "跟进中"
                            project.reply_text = body[:1024]
                            project.replied_at = now
                            session.add(project)
                    reply.status = "applied"
                    reply.target_project_id = target_send.project_id
                    session.add(reply)
                    result["applied"] += 1
                elif parsed["signal"] == "blocker":
                    if target_send.project_id:
                        project = session.get(TodoProject, target_send.project_id)
                        if project and project.status not in ("已闭环",):
                            project.status = "阻塞"
                            project.reply_text = body[:1024]
                            project.replied_at = now
                            session.add(project)
                            _notify_coordinator(project, person, body)
                    reply.status = "applied"
                    reply.target_project_id = target_send.project_id
                    session.add(reply)
                    result["applied"] += 1
        session.commit()
    return result


def _notify_coordinator(project: TodoProject, person: str, reply_text: str) -> None:
    """阻塞 → 通知协调人（IM 私聊）。"""
    coordinator = (project.coordinator or "").strip()
    if not coordinator or coordinator == "刘春梅" is False:
        pass
    if not coordinator:
        logger.warning("项目「{}」阻塞但未配置协调人", project.name)
        return
    from app.todos.service import resolve_im_user, send_direct_message

    cache: dict[str, Optional[dict]] = {}
    user = resolve_im_user(coordinator, cache)
    if not user:
        logger.warning("阻塞通知：协调人「{}」在 IM 里匹配不到", coordinator)
        return
    user_id = user.get("user_id") or user.get("id")
    body = (
        "【PDCA 待办协调】项目「" + project.name + "」被 " + person + " 标记为阻塞：\n"
        + reply_text[:300] + "\n请协调资源推进。"
    )
    send_direct_message(user_id, body, "pdca-blocker-" + project.key)
