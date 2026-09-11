# -*- coding: utf-8 -*-
"""群认领采集：群知会后，谁在群里回复「领取/认领/收到」即视为该人
当日待办全部已认领（知情），记录 claimed_at；整人认领口径。

游标：todo_group_state.last_claim_message_id —— 每次采集只处理该消息
之后的新群消息，处理完推进游标（幂等，重试不重复标记）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.models.todo_group_state import TodoGroupState
from app.statuses import is_done as _is_done
from app.todos.owners import split_owners
from app.vertu.client import run_vertu_sync_json

CLAIM_PATTERNS = re.compile(
    r"(领取|认领|收到|已领|领了|claim|确认收到|收到待办)",
    re.IGNORECASE,
)

USER_ID_CACHE: dict[int, Optional[str]] = {}


def _user_name(user_id: int) -> Optional[str]:
    """user_id → 姓名（HR 人员目录，进程内缓存）。"""
    if user_id in USER_ID_CACHE:
        return USER_ID_CACHE[user_id]
    payload = run_vertu_sync_json(
        ["hr", "+personnel-info", "--user-id", str(user_id), "--limit", "1"],
        timeout=25.0,
    )
    name: Optional[str] = None
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("rows") or []
    if rows and isinstance(rows[0], dict):
        name = rows[0].get("name") or None
    USER_ID_CACHE[user_id] = name
    return name


def _get_state(session: Session, key: str, default: str = "") -> str:
    row = session.exec(
        select(TodoGroupState).where(TodoGroupState.key == key)
    ).first()
    return row.value if row else default


def _set_state(session: Session, key: str, value: str) -> None:
    row = session.exec(
        select(TodoGroupState).where(TodoGroupState.key == key)
    ).first()
    if row is None:
        row = TodoGroupState(key=key, value=value)
        session.add(row)
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
        session.add(row)


def collect_group_claims(today: str, dry_run: bool = False) -> dict:
    """读取群知会后的新消息，解析认领并标记 claimed_at。返回统计。"""
    settings = get_settings()
    channel_id = settings.todo_group_channel_id
    if not channel_id:
        return {"ok": False, "reason": "未配置 PDCA_TODO_GROUP_CHANNEL_ID"}
    cursor = ""
    with Session(get_engine()) as session:
        cursor = _get_state(session, "last_claim_message_id")
    payload = run_vertu_sync_json(
        ["im", "+history", "--channel-id", channel_id, "--limit", "60"],
        timeout=25.0,
    )
    messages = []
    if isinstance(payload, dict):
        messages = payload.get("messages") or []
    new_messages = []
    newest_id = ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_id = str(msg.get("id") or "")
        if cursor and msg_id == cursor:
            break  # 历史按时间倒序，遇到游标即停
        if not newest_id and msg_id:
            newest_id = msg_id
        new_messages.append(msg)
    new_messages.reverse()  # 回到时间正序

    claimed_people: list[dict] = []
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        for msg in new_messages:
            sender_id = msg.get("sender_user_id")
            body = str(msg.get("body") or "")
            if not sender_id or CLAIM_PATTERNS.search(body) is None:
                continue
            name = _user_name(int(sender_id))
            if not name:
                continue
            # 别名归属：丁晓茜认领 == Sissi 名下待办也认领（如 Sissi → 丁晓茜）
            alias_names = {
                alias
                for alias, target in get_settings().todo_owner_aliases.items()
                if target.casefold() == name.casefold()
            }
            rows = list(
                session.exec(
                    select(PdcaTask).where(
                        (
                            (PdcaTask.owner == name)
                            | func.lower(PdcaTask.owner).in_(
                                [alias.casefold() for alias in alias_names]
                            )
                            | PdcaTask.owner.contains("&")
                            | PdcaTask.owner.contains("＆")
                        ),
                        PdcaTask.task_date <= today,
                        PdcaTask.claimed_at.is_(None),
                    )
                ).all()
            )
            # 「A&B」合并负责人：任一人认领即视为该条已认领（整人认领口径）
            match_names = {name.casefold(), *alias_names}
            rows = [
                row for row in rows
                if any(part.casefold() in match_names for part in split_owners(row.owner))
            ]
            open_rows = [row for row in rows if not _is_done(row.status)]
            if not open_rows:
                continue
            for row in open_rows:
                row.claimed_at = now
                row.updated_at = datetime.utcnow()
                session.add(row)
            claimed_people.append(
                {"owner": name, "tasks": len(open_rows), "reply": body[:80]}
            )
        if newest_id:
            _set_state(session, "last_claim_message_id", newest_id)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    # 群聊隐式任务抽取（管理者随口布置 → 待办），与认领共用同一批新消息
    implicit = {}
    if new_messages:
        from app.todos.implicit import extract_implicit_tasks

        implicit = extract_implicit_tasks(new_messages, dry_run=dry_run)
    return {
        "ok": True,
        "channel_id": channel_id,
        "scanned": len(new_messages),
        "claimed_people": claimed_people,
        "implicit": implicit,
        "dry_run": dry_run,
    }
