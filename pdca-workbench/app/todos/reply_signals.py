# -*- coding: utf-8 -*-
"""待办回复的最小、可解释语义分类。"""
from __future__ import annotations

import re
from typing import Optional

DONE_WORDS = ("已完成", "搞定", "做完", "完成", "done", "finished", "closed")
PROGRESS_WORDS = ("推进", "进展", "进行中", "in progress", "处理中", "做了")
BLOCKED_WORDS = ("阻塞", "卡住", "卡在", "blocked", "受阻", "做不了")

_NEGATED_DONE = re.compile(
    r"(?:未|没有?|尚未|还没|无法|不能|不)\s*(?:能\s*)?(?:完成|搞定|做完)"
    r"|\b(?:not(?:\s+yet)?|isn['’]?t|haven['’]?t|hasn['’]?t|didn['’]?t|cannot|can['’]?t)"
    r"\s+(?:done|finished|closed|complete(?:d)?)\b",
    re.IGNORECASE,
)


def classify_reply(reply_text: str) -> Optional[str]:
    text = (reply_text or "").casefold().strip()
    if not text:
        return None
    if any(word in text for word in BLOCKED_WORDS):
        return "blocked"
    if _NEGATED_DONE.search(text):
        return "reply"
    if any(word in text for word in DONE_WORDS):
        return "done"
    if any(word in text for word in PROGRESS_WORDS):
        return "progress"
    return "reply"
