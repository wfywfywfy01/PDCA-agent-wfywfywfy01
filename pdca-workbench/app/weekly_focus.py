# -*- coding: utf-8 -*-
"""本周任务：按人挂一周的任务，三追每版带一节，过期自动收起。

老板 2026-10-10：尤文静 / 杨晶晶 / Lina 这周都要对标「佳佳说」做 AI 视频 →
不用每天重挂，写成一周一条，命中日期就每天追。

- 数据源 app/weekly_focus.json（bundled）；data/runtime/weekly_focus.json 存在时优先（换任务不用发版）；
- 命中规则：start <= day <= end（闭区间），再按 who/aliases 与 groups 命中人；
- 没命中就不出这一节（不写「无」、不编造）。
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from app.config import get_settings

FOCUS_FILE = Path(__file__).with_name("weekly_focus.json")

#: 节标题的英文写法（英文群用 text_en，没给就回落中文原话）
_EN_LABEL = {"本周任务": "This week's assignment"}


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("本周任务读取失败（{}）：{}", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload() -> dict:
    """运行时文件优先（老板改任务不用发版），否则读包内默认。"""
    try:
        override = get_settings().data_dir / "runtime" / "weekly_focus.json"
    except Exception:  # noqa: BLE001 — 配置没起来时用包内默认
        override = None
    if override is not None and override.exists():
        data = _read(override)
        if data:
            return data
    return _read(FOCUS_FILE)


def week_for(day: str) -> dict | None:
    """命中 day 所在的那一周（start/end 闭区间，YYYY-MM-DD 字符串比较）。"""
    if not day:
        return None
    for week in _payload().get("weeks") or []:
        if not isinstance(week, dict):
            continue
        start = str(week.get("start") or "")
        end = str(week.get("end") or "")
        if start and end and start <= day <= end:
            return week
    return None


def items_for(day: str, group_name: str, display: str) -> list[dict]:
    """某人某群当天该看到的本周任务条目。"""
    week = week_for(day)
    if not week:
        return []
    out: list[dict] = []
    for item in week.get("items") or []:
        if not isinstance(item, dict):
            continue
        who = str(item.get("who") or "").strip()
        aliases = {str(alias) for alias in (item.get("aliases") or [])}
        groups = {str(name) for name in (item.get("groups") or [])}
        if who and who != display and display not in aliases:
            continue
        if groups and group_name not in groups:
            continue
        if not str(item.get("text") or "").strip():
            continue
        out.append(item)
    return out


def render(items: list[dict], *, lang: str = "zh", label: str = "本周任务") -> str:
    """拼「本周任务」一节；没有条目返回空串（调用方据此不输出）。"""
    if not items:
        return ""
    head = f"【{label}】" if lang != "en" else f"[{_EN_LABEL.get(label, 'This week')}]"
    lines = [head]
    for item in items:
        text = str(item.get("text_en") or "").strip() if lang == "en" else ""
        lines.append("   • " + (text or str(item.get("text") or "").strip()))
    return "\n".join(lines)


def block_for(day: str, group_name: str, display: str, *, lang: str = "zh") -> str:
    """给单人一条消息用的本周任务正文（可能为空串）。"""
    week = week_for(day) or {}
    label = str(week.get("label") or "本周任务")
    return render(items_for(day, group_name, display), lang=lang, label=label)
