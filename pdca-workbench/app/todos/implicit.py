# -*- coding: utf-8 -*-
"""群聊隐式任务抽取：管理者在群里随口布置的任务自动变成待办。

规则（对齐研发侧「隐式任务抽取」）：
- 仅管理者（付汪阳/刘春梅）发送的消息参与抽取；
- 两种形态：@人 + 事项；让/叫/请/安排 人 + 动词 + 事项；
- 截止日：今天/明天/后天/周X/月日（缺省今天）；
- 负责人必须是已知在跟进的人（别名归一），否则跳过防噪音；
- 同标题同负责人幂等，不重复建。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.statuses import is_done as _is_done

MANAGER_USER_IDS = {13365, 12564}  # 付汪阳 / 刘春梅

# 别名归一：来自 sop.PEOPLE 的已知口径（丽娜=DEHDAHOUMAIMA，Sissi=丁晓茜）
OWNER_ALIASES = {
    "lina": "DEHDAHOUMAIMA",
    "丽娜": "DEHDAHOUMAIMA",
    "sissi": "丁晓茜",
}

ASSIGN_RE = re.compile(
    r"(?:让|叫|请|安排)\s*(?P<who>[^\s，。,]{2,6})"
    r"\s*(?:尽快|记得)?(?:负责|跟进|去|来)?"
    r"\s*(?P<verb>完成|做|输出|整理|处理|确认|对接|推动|提交|核对|盘点|联系|沟通|跟)"
    r"(?P<what>[^\s。]{2,60})"
)
AT_RE = re.compile(r"@(?P<who>[A-Za-z0-9_\-\u4e00-\u9fff]{2,10})\s+(?P<what>[^\s@。]{3,80})")

DEADLINE_RE = re.compile(r"(今天|明天|后天|周[一二三四五六日天]|(\d{1,2})月(\d{1,2})[日号]?|\d{1,2}[./]\d{1,2})")


def _resolve_owner(who: str) -> Optional[str]:
    """负责人 → 已知口径姓名；非在跟进人员返回 None。"""
    key = (who or "").strip().casefold()
    known = {
        "dehdahoumaima", "lina", "丽娜",
        "丁晓茜", "sissi", "于冰", "付汪阳", "何海文", "冯磊", "刘春梅", "刘雪梅",
        "尤文静", "张倩", "张慧", "张琪", "李浩然", "李浩然-1", "杨晶晶", "王宇彤",
        "谢涛", "邓琳莹", "safae",
    }
    if key in OWNER_ALIASES:
        return OWNER_ALIASES[key]
    if key == "李浩然":
        return "李浩然-1"
    if key == "safae":
        return "Safae"
    if key in known:
        return who.strip()
    return None


def _deadline_for(text: str, now: datetime) -> str:
    """从消息里解析截止日；缺省今天。"""
    t = text or ""
    if "今天" in t:
        return now.strftime("%Y-%m-%d")
    if "明天" in t:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if "后天" in t:
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")
    week = re.search(r"周([一二三四五六日天])", t)
    if week:
        day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        target = day_map[week.group(1)]
        delta = (target - now.weekday()) % 7 or 7
        return (now + timedelta(days=delta)).strftime("%Y-%m-%d")
    md = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", t)
    if md:
        month, day = int(md.group(1)), int(md.group(2))
        year = now.year if month >= now.month else now.year + 1
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _candidates(body: str) -> list[tuple[str, str]]:
    """消息正文 → [(负责人, 事项)]。"""
    out: list[tuple[str, str]] = []
    for m in AT_RE.finditer(body):
        who = _resolve_owner(m.group("who"))
        what = m.group("what").strip(" ，,、:")
        if who and len(what) >= 3:
            out.append((who, what))
    for m in ASSIGN_RE.finditer(body):
        who = _resolve_owner(m.group("who"))
        what = (m.group("verb") + m.group("what")).strip()
        if who and len(what) >= 4:
            out.append((who, what))
    return out


def _already_exists(session: Session, owner: str, title: str) -> bool:
    norm = re.sub(r"[\s，,。.!！?？;；:：()（）'\"“”‘’]+", "", title).casefold()
    rows = session.exec(
        select(PdcaTask).where(
            PdcaTask.owner == owner,
            PdcaTask.source == "group-implicit",
        )
    ).all()
    for row in rows:
        if not _is_done(row.status) and re.sub(
            r"[\s，,。.!！?？;；:：()（）'\"“”‘’]+", "", row.title
        ).casefold() == norm:
            return True
    return False


def extract_implicit_tasks(messages: list[dict], dry_run: bool = False) -> dict:
    """从群消息抽取隐式任务建待办；返回统计。"""
    created = 0
    skipped = 0
    now = datetime.now()
    with Session(get_engine()) as session:
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            sender = msg.get("sender_user_id")
            if sender not in MANAGER_USER_IDS:
                continue
            body = str(msg.get("body") or "").strip()
            if not body or len(body) > 300:
                continue
            for owner, what in _candidates(body):
                if _already_exists(session, owner, what):
                    skipped += 1
                    continue
                row = PdcaTask(
                    task_date=_deadline_for(body, now),
                    title=what[:200],
                    owner=owner,
                    status="pending",
                    priority="normal",
                    source="group-implicit",
                    meeting_name="群聊抽取",
                )
                if not dry_run:
                    session.add(row)
                    created += 1
                    logger.info("隐式任务: {} -> {}", owner, what[:60])
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return {"created": created, "skipped": skipped, "dry_run": dry_run}
