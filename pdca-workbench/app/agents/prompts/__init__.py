# -*- coding: utf-8 -*-
"""Agent prompt 模板包：prompt 只引用规则版本，确定性规则留在 Python 代码。"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _load(name: str) -> str:
    path = _DIR / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_group() -> str:
    """群 Agent 系统提示（group.md）。"""
    return _load("group.md")


def load_supervisor() -> str:
    """主 Agent 系统提示（supervisor.md）。"""
    return _load("supervisor.md")


def load() -> str:
    """兼容旧引用：默认返回群 Agent 提示。"""
    return load_group()
