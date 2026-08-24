# -*- coding: utf-8 -*-
"""任务完成状态共享常量（评审整改：消除五处重复定义）。"""
from __future__ import annotations

DONE_STATUSES = ("done", "completed", "complete", "已完成", "完成")


def is_done(status: str | None) -> bool:
    """判断任务状态是否视为已完成。"""
    return str(status or "").strip().casefold() in DONE_STATUSES
