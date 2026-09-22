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


def review_owner_detail(owner_name: str, day: str, *, force: bool = False) -> dict:
    """按人+日期做 MTO 明细核对（后台/主 Agent 统一口径）。

    每张图一行：文件 / 机型 / SKU / 报价（USD、万元）/ 是否达标 / 交期 / 客户，
    并给出当日汇总（张数、达标款数、未满 30 万、未读出、4 款目标是否达成）。
    事实只来自群消息附件 + OCR 结果；读不出写“待确认”，绝不编造金额。
    """
    from app.duzhan_ledger import (
        OWNERS,
        _history_ids,
        fetch_channel_history,
        messages_on_day,
        parse_mto_images,
    )
    from app.mto_ocr import review_mto_images

    owner = next((item for item in OWNERS if item.display == owner_name), None)
    if owner is None:
        return {"owner": owner_name, "day": day, "error": "负责人不在班组注册表"}
    if not owner.im_user_id:
        return {"owner": owner_name, "day": day, "error": "该负责人缺少 IM user_id，无法定位图片"}

    cache_key = f"detail:{owner_name}:{day}"
    now_mono = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and not force and now_mono - cached[0] < 3600:
            return cached[1]

    result: dict = {
        "owner": owner_name,
        "group": owner.group,
        "day": day,
        "channel_id": getattr(owner, "follow_channel_id", "") or "",
        "rows": [],
        "images": 0,
        "qualified": 0,
        "under_threshold": 0,
        "unread": 0,
        "goal": MTO_DAILY_GOAL,
        "goal_met": False,
    }
    try:
        # 与督战采集同源：达标群 + 跟进群（_history_ids）全部拉取后合并，
        # 之前只用 follow_channel_id（可能为空）导致图片数为 0。
        channel_ids = list(_history_ids(owner))
        result["channel_ids"] = channel_ids
        raw_messages: list = []
        for channel_id in channel_ids:
            raw_messages.extend(fetch_channel_history(channel_id, day, "300"))
        messages = messages_on_day(raw_messages, day, owner_group_timezone(owner))
        image_count, file_names = parse_mto_images(messages, owner.im_user_id)
        quote_count, _names, quotes = review_mto_images(messages, owner.im_user_id)
    except Exception as exc:  # noqa: BLE001 — 单源失败写待确认，不抛
        logger.warning("MTO 明细核对失败 owner={} day={}: {}", owner_name, day, exc)
        result["error"] = f"采集失败: {str(exc)[:200]}"
        return result

    for index, quote in enumerate(quotes or []):
        usd = quote.get("usd")
        wan = quote.get("wan")
        raw_ok = bool(quote.get("raw_ok"))
        qualifies = quote.get("qualifies")
        model_text = str(quote.get("model") or "").strip()
        row = {
            "file": file_names[index] if index < len(file_names or []) else "",
            # 型号是硬要求（老板 2026-09-19）：读不出就显式标红，别写“VERTU”糊弄
            "model": model_text or "型号读不出",
            "model_missing": (not model_text) or bool(quote.get("model_missing")),
            "sku": quote.get("sku") or "",
            "usd": usd,
            "wan": wan,
            "qualifies": bool(qualifies),
            "delivery": quote.get("delivery") or "",
            "customer": quote.get("target_customer") or "",
            "verdict": (
                "达标"
                if qualifies
                else ("未满30万" if (raw_ok and wan is not None) else "未读出报价")
            )
            + ("（型号读不出，需人工确认）" if not model_text else ""),
        }
        result["rows"].append(row)
        if row["qualifies"]:
            result["qualified"] += 1
        elif raw_ok and wan is not None:
            result["under_threshold"] += 1
        else:
            result["unread"] += 1
    result["images"] = image_count if image_count is not None else len(result["rows"])
    result["goal_met"] = result["qualified"] >= MTO_DAILY_GOAL
    with _cache_lock:
        _cache[cache_key] = (now_mono, result)
    return result


def owner_group_timezone(owner) -> str:
    """负责人所在群时区：按达标群注册表取群时区（缺省北京时间）。"""
    try:
        from app.duzhan import GROUPS

        group_name = str(getattr(owner, "group", "") or "")
        for group in GROUPS:
            if group.name == group_name:
                return group.tz
    except Exception as exc:  # noqa: BLE001
        logger.debug("群时区解析失败 {}: {}", owner, exc)
    return "Asia/Shanghai"


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
