# -*- coding: utf-8 -*-
"""日报证据匹配（移植自 todo-tracker.mjs）。

Vemory 待办催办前，拉取负责人最近 7 天日报摘要（vertu-cli report
+user-summary），用轻量关键词规则判断是否有跟进证据：有证据暂缓催办，
无证据才催。英文词 + 中文二字片段，停用词过滤，不引入额外依赖。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from app.config import get_settings
from app.todos.vemory import load_vemory_users
from app.vertu.client import run_vertu_sync

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{2,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")

_STOP_WORDS = {
    "继续", "跟进", "一下", "这个", "相关", "进行", "项目", "我们", "他们",
    "需要", "安排", "情况", "推进", "工作", "今天", "之后", "完成", "处理",
    "一起", "问题", "一个", "已经",
}


def evidence_tokens(text: str) -> set[str]:
    """提取英文词与中文二字片段（去停用词、去重），与 todo-tracker.mjs 一致。"""
    latin = _LATIN_RE.findall(text or "")
    cjk: list[str] = []
    for run in _CJK_RUN_RE.findall(text or ""):
        cjk.extend(run[i : i + 2] for i in range(max(0, len(run) - 1)))
    return {token for token in [*latin, *cjk] if token not in _STOP_WORDS}


def has_followup(content: str, report_text: str) -> bool:
    """待办文本与日报摘要是否检出跟进证据。

    规则同 todo-tracker.mjs：任一 >=3 字符的命中，或 >=2 个命中即视为
    有跟进（英文词天然 >=3 字符，中文二字片段需两条）。
    """
    tokens = evidence_tokens(content or "")
    hits = [token for token in tokens if token in (report_text or "")]
    return any(len(token) >= 3 for token in hits) or len(hits) >= 2


def load_vps_user_map() -> dict[str, int]:
    """姓名 → VPS 用户 ID（来自 PDCA_VEMORY_TODO_USERS 名单）。"""
    result: dict[str, int] = {}
    for item in load_vemory_users():
        name = str(item.get("name") or "").strip()
        vps_id = item.get("vpsUserId")
        if name and isinstance(vps_id, int) and vps_id > 0:
            result[name] = vps_id
    return result


def fetch_report_text(
    vps_user_id: int,
    start_day: str,
    end_day: str,
    cache: dict[int, Optional[str]],
) -> Optional[str]:
    """拉取日报摘要；失败/不可用返回 None（不抛异常）。按用户缓存。"""
    if vps_user_id in cache:
        return cache[vps_user_id]
    code, stdout, stderr = run_vertu_sync(
        [
            "report", "+user-summary",
            "--user-id", str(vps_user_id),
            "--start-time", start_day,
            "--end-time", end_day,
        ],
        timeout=30.0,
    )
    if code != 0 or not stdout.strip():
        logger.warning(
            "日报摘要不可用 user_id={} code={} stderr={}",
            vps_user_id,
            code,
            (stderr or "")[:120],
        )
        cache[vps_user_id] = None
        return None
    cache[vps_user_id] = stdout
    return stdout


def report_window_days(today: str, days: int = 6) -> tuple[str, str]:
    """日报查询窗口：今天-6 天 ~ 今天（与 todo-tracker 一致）。"""
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    return start, today


def evidence_config() -> dict:
    """供日志/结果标注的证据判定配置。"""
    settings = get_settings()
    return {"window_days": 6, "users_mapped": len(load_vps_user_map())}
