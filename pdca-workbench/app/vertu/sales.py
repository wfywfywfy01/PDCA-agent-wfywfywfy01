# -*- coding: utf-8 -*-
"""通过 vertu-cli 2.x 的业务快捷命令读取销售数据。"""
from __future__ import annotations

import os
from datetime import date as _date, timedelta

from app.vertu.client import run_vertu_json, run_vertu_sync_json


def _date_range(date_text: str, period: str) -> tuple[str, str]:
    today = _date.fromisoformat(date_text) if date_text else _date.today()
    if period in ("day", "today"):
        return str(today), str(today)
    if period == "week":
        return str(today - timedelta(days=today.weekday())), str(today)
    if period == "month":
        return str(today.replace(day=1)), str(today)
    if period == "quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        return str(today.replace(month=quarter_month, day=1)), str(today)
    return str(today), str(today)


def _trend_months(month: str) -> list[dict[str, str]]:
    year, number = int(month[:4]), int(month[5:7])
    result: list[dict[str, str]] = []
    for offset in range(5, -1, -1):
        current = number - offset
        current_year = year
        while current <= 0:
            current += 12
            current_year -= 1
        next_month = current + 1 if current < 12 else 1
        next_year = current_year if current < 12 else current_year + 1
        result.append(
            {
                "label": f"{current_year:04d}-{current:02d}",
                "start": f"{current_year:04d}-{current:02d}-01",
                "end": str(_date(next_year, next_month, 1) - timedelta(days=1)),
            }
        )
    return result


_PERIOD_LABEL = {
    "day": "今日",
    "today": "今日",
    "week": "本周",
    "month": "本月",
    "quarter": "本季度",
}


async def _headline(start: str, end: str, department: str = "") -> dict:
    args = [
        "sales",
        "+headline-kpi",
        "--start-date",
        start,
        "--end-date",
        end,
    ]
    dept_l1 = os.environ.get("PDCA_VERTU_DEPT_L1", "海外渠道").strip()
    if dept_l1:
        args += ["--dept-l1", dept_l1]
    if department:
        args += ["--dept-l2", department]
    payload = await run_vertu_json(args, timeout=45.0)
    if not isinstance(payload, dict):
        raise RuntimeError("vertu-cli sales +headline-kpi 未返回 JSON")
    return payload


async def fetch_sell_in(date_text: str, period: str = "day") -> dict:
    """Sell-in KPI：按配置的经销商部门聚合 vertu-cli 销售口径。"""
    start, end = _date_range(date_text, period)
    configured = os.environ.get(
        "PDCA_VERTU_SELLIN_DEPARTMENTS",
        "经销商一部,经销商二部,经销商三部",
    )
    departments = [item.strip() for item in configured.split(",") if item.strip()]
    payloads = [await _headline(start, end, department) for department in departments]
    if not payloads:
        payloads = [await _headline(start, end)]
    amount = sum(float((item.get("period") or {}).get("销额") or 0) for item in payloads)
    quantity = sum(int((item.get("period") or {}).get("销量") or 0) for item in payloads)
    label = _PERIOD_LABEL.get(period, "当前区间")
    return {
        "amount": amount,
        "wan": round(amount / 10000, 2),
        "quantity": quantity,
        "note": f"{label}实时 · vertu-cli sales",
    }


async def fetch_sell_out(date_text: str, period: str = "day") -> dict:
    """vertu-cli 2.x 暂无代理商终端 Sell-out 快捷命令，交由本地实报数据兜底。"""
    del date_text, period
    raise RuntimeError("vertu-cli 暂未提供 dealer sell-out 数据源")


def _row_dict(row, columns: list[str]) -> dict:
    if isinstance(row, dict):
        return row
    if isinstance(row, list):
        return {columns[index]: value for index, value in enumerate(row) if index < len(columns)}
    return {}


def fetch_dealer_sales_orders_sync(start: str, end: str) -> dict:
    """通过 vertu-cli 订单快捷命令按客户聚合经销商销售数据。"""
    payload = run_vertu_sync_json(
        [
            "sales",
            "+orders",
            "--start-date",
            start,
            "--end-date",
            end,
            "--dept-l1",
            os.environ.get("PDCA_VERTU_DEPT_L1", "海外渠道"),
            "--limit",
            "5000",
        ],
        timeout=90.0,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("vertu-cli sales +orders 未返回数据")
    columns = [str(item) for item in payload.get("columns") or []]
    grouped: dict[str, dict] = {}
    for raw in payload.get("rows") or []:
        row = _row_dict(raw, columns)
        name = str(row.get("客户名称") or row.get("客户") or "").strip()
        if not name:
            continue
        item = grouped.setdefault(name, {"dealer_name": name, "sell_out_yuan": 0.0, "qty": 0})
        item["sell_out_yuan"] += float(row.get("金额") or 0)
        item["qty"] += int(float(row.get("数量") or 0))
    dealers = sorted(grouped.values(), key=lambda item: -item["sell_out_yuan"])
    return {
        "ok": True,
        "start_date": start,
        "end_date": end,
        "month": end[:7],
        "total": round(sum(float(item["sell_out_yuan"]) for item in dealers), 2),
        "dealers": dealers,
        "source": "vertu-cli sales +orders",
        "source_metric": "dealer_sales",
    }


async def _orders(start: str, end: str) -> dict:
    payload = await run_vertu_json(
        [
            "sales",
            "+orders",
            "--start-date",
            start,
            "--end-date",
            end,
            "--limit",
            "5000",
        ],
        timeout=60.0,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("vertu-cli sales +orders 未返回 JSON")
    return payload


async def fetch_sellin_summary(month: str | None = None) -> dict:
    """按客户汇总当月 Sell-in，并给出最近六个月趋势。"""
    month = month or _date.today().strftime("%Y-%m")
    months = _trend_months(month)
    current = await _orders(months[-1]["start"], months[-1]["end"])
    columns = [str(item) for item in current.get("columns") or []]
    grouped: dict[str, dict] = {}
    for raw in current.get("rows") or []:
        row = _row_dict(raw, columns)
        name = str(row.get("客户名称") or row.get("客户") or "").strip()
        if not name:
            continue
        item = grouped.setdefault(name, {"name": name, "amount": 0.0, "quantity": 0})
        item["amount"] += float(row.get("金额") or 0)
        item["quantity"] += int(float(row.get("数量") or 0))
    ordered = sorted(grouped.values(), key=lambda item: -item["amount"])
    dealers = [
        {
            "rank": index + 1,
            "name": item["name"],
            "wan": round(item["amount"] / 10000, 2),
            "quantity": item["quantity"],
        }
        for index, item in enumerate(ordered[:50])
    ]

    trend: list[dict] = []
    for item in months:
        payload = current if item is months[-1] else await _orders(item["start"], item["end"])
        amount = float((payload.get("summary") or {}).get("amount") or 0)
        trend.append({"month": item["label"], "wan": round(amount / 10000, 2)})
    total = sum(float(item["amount"]) for item in ordered)
    return {
        "month": month,
        "total_wan": round(total / 10000, 2),
        "dealers": dealers,
        "has_data": bool(dealers),
        "trend": trend,
        "source": "vertu-cli sales +orders",
    }
