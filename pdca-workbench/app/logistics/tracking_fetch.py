# -*- coding: utf-8 -*-
"""从承运商官网抓取物流实时状态（UPS / FedEx / DHL）。

顺丰（SF）官网查询强制图形验证码，无法可靠自动化，不在支持范围内——
调用方应继续保留 SF 运单的人工 current_status 录入。

抓取策略：不依赖易变的页面选择器，而是取整页可见文本，按优先级匹配
与人工录入口径一致的状态关键词（见 config/settings.json 的
logistics.normal_keywords / abnormal_keywords），兼容官网改版。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger
from playwright.async_api import async_playwright

_SUPPORTED_CARRIERS = {"ups", "fedex", "dhl"}

_TRACK_URL = {
    "ups": "https://www.ups.com/track?loc=en_US&tracknum={tn}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={tn}",
    "dhl": "https://www.dhl.com/global-en/home/tracking.html?tracking-id={tn}",
}

# (状态标签, 是否视为已签收, 匹配关键词——按优先级从高到低)
_PHRASE_PRIORITY: list[tuple[str, bool, list[str]]] = [
    ("Delivered", True, ["delivered", "已签收", "签收"]),
    ("Exception", False, [
        "exception", "delay", "delayed", "held", "returned", "failed",
        "customs clearance", "clearance delay", "异常", "延误", "退回", "派送失败",
    ]),
    ("Out For Delivery", False, ["out for delivery", "派送中"]),
    ("In Transit", False, ["in transit", "on the way", "departed", "arrived at", "运输中"]),
    ("Label Created", False, ["label created", "shipment information sent", "待揽收"]),
    ("Invalid / Not Found", False, [
        "invalid tracking number", "tracking number is invalid", "no record found",
        "we could not locate", "not found", "tracking error",
        "unable to complete your tracking request", "运单号错误",
    ]),
]

_NAV_TIMEOUT_MS = 35_000
_MAX_CONCURRENCY = 3


@dataclass
class FetchResult:
    tracking_number: str
    carrier: str
    status_text: str = ""
    is_delivered: bool = False
    fetch_ok: bool = False
    error: str = ""


def is_supported_carrier(carrier: str) -> bool:
    return (carrier or "").strip().lower() in _SUPPORTED_CARRIERS


# 页脚/导航/营销内容常见标记词——在此之后的文本一律裁掉，避免像 DHL 页脚的
# "Delivered Magazine" 误判成运单已签收这类假阳性。真实查询结果永远渲染在
# 页面顶部表单区域，出现在这些标记词之前。
_FOOTER_MARKERS = [
    "frequently asked questions", "quick links", "follow us",
    "company information", "all rights reserved", "unbox your potential",
    "stop tracking the box", "our divisions", "industry sectors",
]


def _clip_before_footer(text: str) -> str:
    lower = text.lower()
    cut_at = len(text)
    for marker in _FOOTER_MARKERS:
        idx = lower.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)
    return text[:cut_at]


def _match_status(body_text: str) -> tuple[str, bool] | None:
    clipped = _clip_before_footer(body_text)
    lower = clipped.lower()
    for label, delivered, keywords in _PHRASE_PRIORITY:
        for kw in keywords:
            if kw in lower:
                return label, delivered
    return None


_POLL_ATTEMPTS = 10
_POLL_INTERVAL_MS = 2_000


async def _poll_for_content(page) -> str:
    """UPS 等 SPA 渲染时机很不稳定（实测最长要 12-14 秒才出真实结果，期间会经过
    CSS 占位符、空白、局部渲染等过渡态），轮询直到命中状态关键词或轮询预算耗尽。
    """
    best_text = ""
    for _ in range(_POLL_ATTEMPTS):
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if text and len(text) > len(best_text):
            best_text = text
        if _match_status(text):
            return text
        await page.wait_for_timeout(_POLL_INTERVAL_MS)
    return best_text


async def _fetch_one(browser, carrier: str, tracking_number: str) -> FetchResult:
    key = carrier.strip().lower()
    url_template = _TRACK_URL.get(key)
    result = FetchResult(tracking_number=tracking_number, carrier=carrier)
    if not url_template:
        result.error = f"不支持的承运商: {carrier}"
        return result

    page = await browser.new_page()
    try:
        url = url_template.format(tn=tracking_number)
        try:
            await page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as exc:
            # SPA 页面常在 domcontentloaded 后仍继续渲染，超时不代表失败，继续尝试读取内容
            logger.debug("{} {} 导航超时/异常，继续读取已渲染内容: {}", carrier, tracking_number, exc)
        body_text = await _poll_for_content(page)
        matched = _match_status(body_text)
        if matched:
            label, delivered = matched
            result.status_text = label
            result.is_delivered = delivered
            result.fetch_ok = True
        else:
            result.error = "未能从页面识别出状态关键词"
    except Exception as exc:
        result.error = str(exc)[:200]
        logger.warning("抓取物流状态失败 {} {}: {}", carrier, tracking_number, exc)
    finally:
        await page.close()
    return result


async def _launch_browser(pw):
    """默认使用无头模式，保证后台服务和容器没有桌面会话时仍能运行。"""
    import os

    headless = os.environ.get("PDCA_TRACKING_HEADLESS", "1") == "1"
    try:
        return await pw.chromium.launch(headless=headless, channel="chrome")
    except Exception as exc:
        logger.warning("未找到系统 Chrome，回退 Playwright 内置 Chromium: {}", exc)
        return await pw.chromium.launch(headless=headless)


async def fetch_many(items: list[tuple[str, str]]) -> list[FetchResult]:
    """批量抓取。items: [(carrier, tracking_number), ...]，自动跳过不支持的承运商。"""
    eligible = [(c, t) for c, t in items if is_supported_carrier(c) and (t or "").strip()]
    if not eligible:
        return []

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    results: list[FetchResult] = []

    async with async_playwright() as pw:
        browser = await _launch_browser(pw)
        try:
            async def _guarded(carrier: str, tracking_number: str) -> FetchResult:
                async with semaphore:
                    return await _fetch_one(browser, carrier, tracking_number)

            results = await asyncio.gather(
                *[_guarded(c, t) for c, t in eligible],
                return_exceptions=False,
            )
        finally:
            await browser.close()
    return list(results)
