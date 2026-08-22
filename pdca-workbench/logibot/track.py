"""Playwright 打开 UPS/DHL 官网查轨迹。"""

from __future__ import annotations

import re
import time

from db import list_trackable, upsert
from notify import notify, notify_user
from status import (
    advance,
    detect_exception,
    display_status,
    event_hash,
    lifecycle_from_text,
    lifecycle_of,
    past_warn,
    warn_date,
)

UPS_URL = "https://www.ups.com/track?tracknum={num}"
DHL_URL = "https://www.dhl.com/global-en/home/tracking.html?tracking-id={num}"


def _carrier_of(row: dict) -> str:
    num = (row.get("国际单号") or "").replace(" ", "").upper()
    name = row.get("快递公司") or ""
    if num.startswith("1Z") or "UPS" in name:
        return "UPS"
    if "DHL" in name:
        return "DHL"
    return name or "UNKNOWN"


def _status_from_text(text: str, row: dict) -> tuple[str, str, str, str]:
    """从页面正文得到生命周期、异常、展示状态、摘录。
    @param {str} text
    @param {dict} row
    @returns {tuple} (生命周期, 异常, 签收状态, 摘录)
    """
    blob = " ".join(text.split())
    snippet = blob[:240]
    life = advance(lifecycle_of(row), lifecycle_from_text(text))
    exc = detect_exception(text)
    if life in ("DELIVERED", "RETURNED"):
        exc = ""
    elif not exc and past_warn(row.get("预警时间（5天）")):
        exc = "NO_EVENT_TIMEOUT"
    return life, exc, display_status(life, exc), snippet


def _track_url(carrier: str, num: str) -> str | None:
    if carrier == "UPS":
        return UPS_URL.format(num=num)
    if carrier == "DHL":
        return DHL_URL.format(num=num)
    return None


def _fetch_page_text(url: str) -> str:
    """无头打开官网，取 body 文本。
    @param {str} url
    @returns {str}
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)
        for label in ("Accept", "I Accept", "Agree", "接受", "同意"):
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            try:
                if btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
        text = page.locator("body").inner_text()
        browser.close()
        return text


def track_one(row: dict) -> dict:
    """查一票国际单，变化才写库并通知。
    @param {dict} row
    @returns {dict}
    """
    num = (row.get("国际单号") or "").replace(" ", "")
    carrier = _carrier_of(row)
    url = _track_url(carrier, num)
    if not url:
        note = (row.get("备注") or "")
        if "该渠道无官网轨迹" not in note:
            upsert(
                {
                    "顺丰单号": row["顺丰单号"],
                    "备注": (note + ";该渠道无官网轨迹").strip(";"),
                },
                overwrite=True,
            )
        return {"顺丰单号": row["顺丰单号"], "status": "skip", "reason": "无官网"}
    text = _fetch_page_text(url)
    life, exc, status, snippet = _status_from_text(text, row)
    digest = event_hash(snippet)
    delivered = None
    if life == "DELIVERED":
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
        if m:
            delivered = m.group(1)
    patch = {
        "顺丰单号": row["顺丰单号"],
        "生命周期": life,
        "异常": exc,
        "签收状态": status,
        "最新轨迹": snippet,
        "事件哈希": digest,
    }
    if delivered:
        patch["签收日期"] = delivered
    if not row.get("预警时间（5天）") and life not in ("DELIVERED", "RETURNED"):
        patch["预警时间（5天）"] = warn_date()
    old_exc = row.get("异常") or ""
    status_changed = row.get("签收状态") != status or old_exc != (exc or "")
    hash_changed = bool(row.get("事件哈希")) and row.get("事件哈希") != digest
    changed = status_changed or hash_changed
    need_write = changed or not row.get("生命周期") or not row.get("事件哈希") or "预警时间（5天）" in patch
    if need_write:
        upsert(patch, overwrite=True)
    if changed:
        msg = (
            f"{row.get('订单号')} {num} {carrier}\n"
            f"{row.get('签收状态')} -> {status}\n"
            f"{snippet[:120]}\n"
            f"官网 {url}"
        )
        notify(msg)
        uid = row.get("im_user_id")
        if uid:
            try:
                notify_user(uid, msg)
            except Exception as exc_im:
                print("notify_user", exc_im)
    return {
        "顺丰单号": row["顺丰单号"],
        "国际单号": num,
        "status": status,
        "生命周期": life,
        "异常": exc,
        "changed": changed,
    }


def track_all(sleep_s: float = 4.0) -> list[dict]:
    """轮询全部可查国际单。
    @param {float} sleep_s
    @returns {list}
    """
    results = []
    rows = list_trackable()
    for i, row in enumerate(rows):
        results.append(track_one(row))
        if i < len(rows) - 1:
            time.sleep(sleep_s)
    return results
