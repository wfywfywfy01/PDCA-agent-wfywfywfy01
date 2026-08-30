# -*- coding: utf-8 -*-
"""每日经营日报：只发布可直接验证的核心数据。"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.database import get_engine
from app.models.walkin_daily_report import WalkinDailyReport
from app.vertu.sales import fetch_sell_in


async def _fetch_live_sales_async(yesterday: str, day: str) -> tuple[dict, dict]:
    return await asyncio.gather(
        fetch_sell_in(yesterday, "day"),
        fetch_sell_in(day, "month"),
    )


def _fetch_live_sales(yesterday: str, day: str) -> tuple[dict, dict]:
    """直接查询销售事实源；历史快照不作为日报事实。"""
    return asyncio.run(_fetch_live_sales_async(yesterday, day))


def _validated_sales(payload: dict, label: str) -> tuple[float, int]:
    if payload.get("state") != "live":
        raise RuntimeError(f"{label} Sell-in 数据源不是实时状态")
    try:
        return float(payload["wan"]), int(payload["quantity"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} Sell-in 返回缺少金额或销量") from exc


def _as_of(payloads: tuple[dict, dict]) -> str:
    latest = max(
        (str(item.get("as_of") or "") for item in payloads if item.get("as_of")),
        default="",
    )
    if not latest:
        return "N/A"
    try:
        return datetime.fromisoformat(latest).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "N/A"


def build_report(day: str) -> str:
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    sales = _fetch_live_sales(yesterday, day)
    yesterday_wan, yesterday_units = _validated_sales(sales[0], "昨日")
    month_wan, month_units = _validated_sales(sales[1], "本月")

    with Session(get_engine()) as session:
        reports = session.exec(
            select(WalkinDailyReport).where(WalkinDailyReport.report_date == yesterday)
        ).all()
    reported_ids = {
        row.dealer_id
        for row in reports
        if row.dealer_id
        and not row.dealer_id.lower().startswith(("qa-", "test-", "demo-"))
    }

    return "\n".join(
        [
            f"📊 PDCA 核心日报 {day}",
            "",
            "【Sell-in｜Vertu 实时查询】",
            f"· 昨日（{yesterday[5:]}）：{yesterday_wan:,.2f} 万 · {yesterday_units} 台",
            f"· 本月累计：{month_wan:,.2f} 万 · {month_units} 台",
            "",
            f"【门店五件套原始回执（{yesterday[5:]}）】",
            f"· 系统收到 {len(reported_ids)} 家门店填报",
            "· 应报门店清单尚未确认，暂不计算完成率和缺报名单",
            "",
            f"数据截至：{_as_of(sales)}",
            "入口：https://pdca-workbench-teams.vertu.cn/app/",
        ]
    )
