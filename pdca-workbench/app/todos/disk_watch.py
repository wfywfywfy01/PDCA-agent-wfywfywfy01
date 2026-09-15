# -*- coding: utf-8 -*-
"""宿主机磁盘水位监测：低水位分级告警，防止磁盘满导致数据库崩溃重演。

主应用容器以只读方式挂载宿主机根目录（/:/host:ro），每 30 分钟检查一次；
低于阈值通过机器人告警管理者。告警本身只读，不做任何数据操作。
"""
from __future__ import annotations

import os
import shutil


def disk_usage(path: str = "/host") -> tuple[int, int, float]:
    """返回 (总量, 可用, 可用占比)；挂载不可用返回 (0, 0, 1.0)。"""
    try:
        if hasattr(os, "statvfs"):
            stat = os.statvfs(path)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
        else:  # Windows 开发环境
            usage = shutil.disk_usage(path)
            total, free = usage.total, usage.free
        return total, free, (free / total if total else 1.0)
    except OSError:
        return 0, 0, 1.0


def levels_for(free_pct: float) -> list[tuple[str, int]]:
    """按可用占比给出告警级别与最小间隔秒数（critical 优先）。"""
    if free_pct < 0.12:
        return [("critical", 6 * 3600)]
    if free_pct < 0.25:
        return [("warning", 24 * 3600)]
    return []
