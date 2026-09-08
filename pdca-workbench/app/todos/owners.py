# -*- coding: utf-8 -*-
"""待办负责人解析：拆分「A&B」合并负责人。"""
from __future__ import annotations

import re

_SPLIT_RE = re.compile(r"[&＆、]+")


def split_owners(owner: str) -> list[str]:
    """把「谢涛&Sissi」拆成独立负责人；无分隔符返回原样（去空格）。

    空字符串返回空列表；每个片段去首尾空白。
    """
    if not owner:
        return []
    parts = [part.strip() for part in _SPLIT_RE.split(owner) if part.strip()]
    return parts or [owner.strip()]


def apply_alias(name: str, aliases: dict[str, str]) -> str:
    """别名 → 规范姓名（如 Sissi → 丁晓茜）；无映射原样返回。

    aliases 键应为小写别名，值为 HR 姓名。
    """
    key = (name or "").strip().casefold()
    if key and key in aliases:
        return str(aliases[key]).strip()
    return (name or "").strip()
