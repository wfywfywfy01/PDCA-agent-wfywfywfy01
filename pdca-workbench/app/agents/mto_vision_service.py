# -*- coding: utf-8 -*-
"""MTO 视觉能力薄封装（第 11 节）：复用 app.mto_ocr，不重写 OCR/去重逻辑。

规则：
- MTO_QUOTE_MIN_WAN = 30：单款报价不低于 30 万才算达标；
- 报价缺失不能算金额达标；无视觉密钥时张数可统计、金额写“待确认”；
- 同图/同款只计一次（由 mto_ocr 现有逻辑负责）；
- 结果写 mto.* 事件并进入任务 evidence，不直接作扣罚决定。
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone

from loguru import logger

from app.agents.events import write_event
from app.agents.schemas import VisionResult
from app.config import get_settings

MTO_QUOTE_MIN_WAN = 30.0
MTO_DAILY_GOAL = 4

# 内存缓存：同一天同一负责人不重复 OCR（10/15/20 三档共用），降低重复计费。
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def quote_to_vision(owner: str, source_ref: str, quote: dict) -> VisionResult:
    """把 mto_ocr.parse_quote_text 的结果映射为 VisionResult 契约。"""
    raw_ok = bool(quote.get("raw_ok"))
    wan = quote.get("wan")
    qualifies = bool(quote.get("qualifies")) if raw_ok else None
    review_status = "verified" if raw_ok else "pending_manual"
    return VisionResult(
        image_id=quote.get("sku") or quote.get("model") or "",
        owner=owner,
        source_ref=source_ref[:256],
        ocr_text=quote.get("model") or "",
        product=quote.get("model") or "机型待确认",
        material=quote.get("delivery") or "",
        color="",
        quote_wan=wan,
        qualifies=qualifies,
        confidence=1.0 if raw_ok else 0.0,
        review_status=review_status,
    )


def review_owner_images(
    owner: str,
    messages: list | None,
    sender_id: int | None,
    *,
    day: str,
    force: bool = False,
) -> dict:
    """复用 review_mto_images，输出结构化结果与证据；带日内缓存。

    无视觉密钥时（settings.qwen_api_key 为空）张数仍可统计，
    金额达标写“待确认”（qualifies=None）。
    """
    from app.mto_ocr import review_mto_images, summarize_quotes

    cache_key = f"{owner}:{day}"
    now_mono = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and not force and now_mono - cached[0] < 3600:
            return cached[1]
    try:
        count, names, quotes = review_mto_images(messages, sender_id)
    except Exception as exc:  # noqa: BLE001 — 单源失败写待确认
        logger.warning("MTO 视觉采集失败 owner={}: {}", owner, exc)
        count, names, quotes = None, [], []
    results: list[dict] = []
    for index, quote in enumerate(quotes or []):
        item = quote_to_vision(owner, f"mto:{day}:{owner}:{index}", quote)
        results.append(item.model_dump())
    qualify_n = sum(1 for item in results if item.get("qualifies"))
    payload = {
        "owner": owner,
        "day": day,
        "count": count,
        "qualify_count": qualify_n,
        "goal": MTO_DAILY_GOAL,
        "goal_met": bool(count is not None and qualify_n >= MTO_DAILY_GOAL),
        "quotes": results[:12],
        "amount_unknown": not get_settings().qwen_api_key,
    }
    write_event(
        "mto.review_completed",
        producer="mto_vision_service",
        event_key=f"mto:review:{owner}:{day}",
        payload=payload,
    )
    with _cache_lock:
        _cache[cache_key] = (now_mono, payload)
    return payload


def image_bytes_sha(content: bytes) -> str:
    """计算图片 SHA-256（供重复图比对与证据引用）。"""
    return _sha256_of(content)
