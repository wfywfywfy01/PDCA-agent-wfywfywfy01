# -*- coding: utf-8 -*-
"""将 FastAPI 表单转为 legacy pdca_workbench 格式。"""
from __future__ import annotations

from starlette.datastructures import FormData


def form_to_legacy(form: FormData) -> dict[str, list[str]]:
    """legacy 期望 form.get(key, [''])[0] 结构。"""
    legacy: dict[str, list[str]] = {}
    for key, value in form.multi_items():
        legacy.setdefault(key, []).append("" if value is None else str(value))
    return legacy
