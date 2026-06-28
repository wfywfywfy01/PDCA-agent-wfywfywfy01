# -*- coding: utf-8 -*-
"""Real sales KPI via vertu skill run, with time-based cache.

Scheduled refresh: 09:00 / 12:00 / 21:00 daily.
Between refreshes, cached data is served. force=True bypasses cache.
"""
from __future__ import annotations

import json
from datetime import datetime, time
from typing import Any

from loguru import logger

from app.vertu.client import run_vertu

_REFRESH_TIMES = [time(9, 0), time(12, 0), time(21, 0)]

# {period: {"data": dict, "fetched_at": datetime}}
_cache: dict[str, dict] = {}

PERIOD_TO_VERTU = {
    "day": "today",
    "week": "this_week",
    "month": "this_month",
    "quarter": "this_quarter",
}


def _last_scheduled(now: datetime) -> datetime:
    import datetime as dt
    today = now.date()
    for t in reversed(_REFRESH_TIMES):
        candidate = datetime.combine(today, t)
        if now >= candidate:
            return candidate
    yesterday = today - dt.timedelta(days=1)
    return datetime.combine(yesterday, _REFRESH_TIMES[-1])


def _is_stale(period: str, now: datetime) -> bool:
    entry = _cache.get(period)
    if not entry:
        return True
    return entry["fetched_at"] < _last_scheduled(now)


async def get_sales_kpi(period: str = "day", force: bool = False) -> dict:
    """Return sell-in KPI. Refreshes if stale or force=True, otherwise serves cache."""
    now = datetime.now()
    if not force and not _is_stale(period, now):
        entry = _cache[period]
        return {**entry["data"], "cached": True, "fetched_at": entry["fetched_at"].isoformat()}
    data = await _fetch(period)
    _cache[period] = {"data": data, "fetched_at": now}
    return {**data, "cached": False, "fetched_at": now.isoformat()}


async def _fetch(period: str) -> dict:
    vertu_period = PERIOD_TO_VERTU.get(period, "today")
    params_json = json.dumps({"period": vertu_period})
    code, stdout, stderr = await run_vertu(
        ["skill", "run", "odoo-daily-sales-report",
         "--script-key", "headline_kpi",
         "--params", params_json],
        timeout=60.0,
    )
    if code != 0:
        logger.warning("sales_kpi vertu failed code={} period={} err={}", code, period, stderr[:200])
        return _empty(period)
    try:
        raw = json.loads(stdout.strip())
        result = (raw.get("execution") or {}).get("result") or {}
        return _parse(result, period)
    except Exception as exc:
        logger.warning("sales_kpi parse error period={}: {}", period, exc)
        return _empty(period)


def _parse(result: Any, period: str) -> dict:
    if not isinstance(result, dict):
        return _empty(period)
    today_data = result.get("today") or {}
    period_data = result.get("period") or {}
    today_amount = float(today_data.get("销额") or 0)
    period_amount = float(period_data.get("销额") or 0)
    today_qty = int(today_data.get("销量") or 0)
    period_qty = int(period_data.get("销量") or 0)
    if period == "day":
        main_amount = today_amount
        main_qty = today_qty
    else:
        main_amount = period_amount
        main_qty = period_qty
    wan = round(main_amount / 10000, 2)
    return {
        "period": period,
        "sell_in_amount": main_amount,
        "sell_in_wan": wan,
        "sell_in_wan_label": f"{wan:.2f}",
        "sell_in_quantity": main_qty,
        "today_amount": today_amount,
        "period_amount": period_amount,
        "time_progress_pct": result.get("time_progress_pct"),
        "summary": result.get("summary", ""),
        "filter_label": (result.get("filter") or {}).get("period", ""),
    }


def _empty(period: str) -> dict:
    return {
        "period": period,
        "sell_in_amount": 0,
        "sell_in_wan": 0,
        "sell_in_wan_label": "—",
        "sell_in_quantity": 0,
        "today_amount": 0,
        "period_amount": 0,
        "time_progress_pct": None,
        "summary": "",
        "filter_label": "",
    }


async def refresh_all() -> None:
    """Proactively refresh all period caches. Called by scheduler at 9:00/12:00/21:00."""
    for period in list(PERIOD_TO_VERTU.keys()):
        try:
            await get_sales_kpi(period=period, force=True)
            logger.info("sales_kpi refresh ok: period={}", period)
        except Exception as exc:
            logger.error("sales_kpi refresh failed period={}: {}", period, exc)
