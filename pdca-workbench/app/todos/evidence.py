# -*- coding: utf-8 -*-
"""日报证据匹配：从部门日报接口（vertu-cli report +department）提取跟进证据。

催办/打分前拉取窗口期内的日报（--all-departments 全公司范围，权限不足时
自动回退本部门），按姓名聚合文本，用轻量关键词规则判断负责人是否有跟进
证据：有证据暂缓催办、打分加分。英文词 + 中文二字片段，停用词过滤，
不引入额外依赖。
"""
from __future__ import annotations

import json
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


_DAILY_TEXT_FIELDS = ("title", "content", "work_name", "task_title")


def _submission_texts(submission: dict) -> list[str]:
    """一条日报提交 → 可检索文本列表（title/content/work_name）。"""
    payload = submission.get("payload") if isinstance(submission, dict) else None
    texts: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                for field in _DAILY_TEXT_FIELDS:
                    text = item.get(field)
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
    return texts


def _parse_department_reports(stdout: str) -> dict[str, dict]:
    """+department 响应 → 姓名(casefold) → {"user_id", "texts"}。"""
    try:
        payload = json.loads(stdout or "")
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    corpus: dict[str, dict] = {}
    for sub in payload.get("submissions") or []:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("employee_name") or "").strip()
        if not name:
            continue
        texts = _submission_texts(sub)
        if not texts:
            continue
        entry = corpus.setdefault(name.casefold(), {"user_id": None, "texts": []})
        if isinstance(sub.get("user_id"), int):
            entry["user_id"] = sub["user_id"]
        entry["texts"].extend(texts)
    return corpus


_CORPUS_CACHE: dict[tuple[str, ...], dict[str, dict]] = {}


def fetch_department_reports(
    dates: list[str], timeout: float = 45.0
) -> dict[str, dict]:
    """按日拉取部门日报并按姓名聚合；单日失败跳过，返回部分结果。

    进程内按日期集合缓存：morning/afternoon 两轮催办共用同一份拉取。
    """
    key = tuple(sorted(set(dates)))
    if key in _CORPUS_CACHE:
        return _CORPUS_CACHE[key]
    corpus: dict[str, dict] = {}
    for date in key:
        code, stdout, stderr = run_vertu_sync(
            [
                "report", "+department", "--date", date,
                "--all-departments", "--limit", "500",
            ],
            timeout=timeout,
        )
        if code != 0:
            # 无全公司日报权限时回退本部门范围
            code, stdout, stderr = run_vertu_sync(
                ["report", "+department", "--date", date, "--limit", "500"],
                timeout=timeout,
            )
        if code != 0 or not (stdout or "").strip():
            logger.warning(
                "部门日报拉取失败 date={} code={} stderr={}",
                date, code, (stderr or "")[:120],
            )
            continue
        parsed = _parse_department_reports(stdout)
        if not parsed:
            logger.warning("部门日报返回为空 date={}", date)
        for name, entry in parsed.items():
            merged = corpus.setdefault(name, {"user_id": None, "texts": []})
            if entry.get("user_id") is not None:
                merged["user_id"] = entry["user_id"]
            merged["texts"].extend(entry.get("texts") or [])
    _CORPUS_CACHE[key] = corpus
    return corpus


def report_text_for(name: str, corpus: dict[str, dict]) -> Optional[str]:
    """负责人姓名 → 窗口期内日报合并文本；未找到返回 None。

    先精确匹配，其次唯一包含匹配（如「冯磊」→「冯磊-1」），不唯一不猜。
    """
    key = (name or "").strip().casefold()
    if not key:
        return None
    entry = corpus.get(key)
    if entry is None:
        loose = [e for k, e in corpus.items() if key in k or k in key]
        entry = loose[0] if len(loose) == 1 else None
    if entry is None:
        return None
    texts = entry.get("texts") or []
    return "\n".join(texts) if texts else None


def date_range(start_day: str, end_day: str) -> list[str]:
    """[start_day, end_day] 逐日 YYYY-MM-DD 列表（含两端）。"""
    start = datetime.strptime(start_day, "%Y-%m-%d")
    end = datetime.strptime(end_day, "%Y-%m-%d")
    days = (end - start).days
    if days < 0:
        return []
    return [
        (start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days + 1)
    ]


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
