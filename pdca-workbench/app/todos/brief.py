# -*- coding: utf-8 -*-
"""每日催收简报：按人分类 已完成/有进度/无回复，附带升级链名单。

对齐研发侧催收员口径：群里/私聊只认负责人本人的回复；催办 ≥3 次仍无
回复的人进入升级名单（管理者线下约谈），不靠自觉。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.statuses import is_done as _is_done
from app.todos.owners import apply_alias, split_owners

ESCALATE_THRESHOLD = 6  # 催办轮次（每天 2 轮 ≈ 3 天）
MIN_STALLED_TASKS = 3    # 至少 3 条停滞任务才进入升级名单


def _group_by_person() -> dict[str, list[PdcaTask]]:
    settings = get_settings()
    skip = {n.strip().casefold() for n in settings.todo_remind_skip_owners if n.strip()}
    aliases = settings.todo_owner_aliases
    grouped: dict[str, list[PdcaTask]] = defaultdict(list)
    with Session(get_engine()) as session:
        rows = list(session.exec(select(PdcaTask)).all())
    for row in rows:
        parts: list[str] = []
        for part in split_owners(row.owner):
            name = apply_alias(part, aliases)
            if name.casefold() not in skip and name not in parts:
                parts.append(name)
        for name in parts:
            grouped[name].append(row)
    return grouped


def build_daily_brief(today: Optional[str] = None) -> str:
    """管理者简报：每人 未完成(有进度/无回复) + 近7天完成 + 升级名单。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime(
        "%Y-%m-%d"
    )
    grouped = _group_by_person()
    lines = [f"【PDCA 待办简报】{today}"]
    escalate: list[str] = []
    for person in sorted(grouped, key=str.casefold):
        rows = grouped[person]
        done7 = sum(
            1 for r in rows
            if _is_done(r.status) and (r.task_date or "") >= cutoff
        )
        open_rows = [r for r in rows if not _is_done(r.status)]
        replied = sum(1 for r in open_rows if r.replied_at)
        noreply = len(open_rows) - replied
        # 停滞任务：已逾期、催办 >= 阈值次、仍无回复
        stalled = [
            r for r in open_rows
            if not r.replied_at
            and (r.remind_count or 0) >= ESCALATE_THRESHOLD
            and (r.task_date or "") < today
        ]
        if len(stalled) >= MIN_STALLED_TASKS:
            escalate.append(person)
        lines.append(
            f"{person}：未完成 {len(open_rows)}（有进度 {replied} / 无回复 {noreply}）"
            f"｜近7天完成 {done7}"
        )
    lines.append("")
    if escalate:
        lines.append(
            f"⚠ 升级提醒（催办≥{ESCALATE_THRESHOLD}次仍无回复，建议线下约谈）："
            + "、".join(escalate)
        )
    else:
        lines.append("升级提醒：无")
    return "\n".join(lines)
