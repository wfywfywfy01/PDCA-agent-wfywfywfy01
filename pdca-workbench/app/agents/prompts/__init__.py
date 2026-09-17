# -*- coding: utf-8 -*-
"""Agent prompt 模板包：prompt 只引用规则版本，确定性规则留在 Python 代码。"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load() -> str:
    """group.md 群 Agent 系统提示（与目录同名的加载约定）。"""
    path = _DIR / "group.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""
