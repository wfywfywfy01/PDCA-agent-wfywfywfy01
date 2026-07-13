# -*- coding: utf-8 -*-
"""集中处理外部输入中的日期和文件路径。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, status

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def require_iso_date(value: str, *, field: str = "date") -> str:
    """只接受真实存在的 YYYY-MM-DD 日期。"""
    if not _ISO_DATE_RE.fullmatch(value or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} 格式应为 YYYY-MM-DD",
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} 不是有效日期",
        ) from exc
    if parsed.isoformat() != value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} 不是有效日期",
        )
    return value


def resolve_file_under(root: Path, rel_path: str) -> Path:
    """解析静态资源，拒绝绝对路径、目录穿越和目录本身。"""
    root_resolved = root.resolve()
    rel = unquote(rel_path or "").replace("\\", "/").lstrip("/")
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        raise HTTPException(status_code=404, detail="文件不存在")
    target = (root_resolved / rel).resolve()
    if not target.is_relative_to(root_resolved) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target
