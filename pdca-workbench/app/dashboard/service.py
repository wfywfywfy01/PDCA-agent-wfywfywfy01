# -*- coding: utf-8 -*-
"""Dashboard 业务服务（委托遗留实现）。"""
from __future__ import annotations

from app.legacy import bridge


def overview(date_text: str, period: str = "day", session_user: dict | None = None) -> dict:
    return bridge.api_dashboard_overview(date_text, period, session_user=session_user)


def sell_in(date_text: str, period: str = "day") -> dict:
    data = overview(date_text, period)
    return {
        "amount": data["sellInAmount"],
        "wan": data["sellInWan"],
        "note": data["sellInSub"],
    }


def sell_out(date_text: str, period: str = "day") -> dict:
    data = overview(date_text, period)
    return {
        "amount": data["sellOutAmount"],
        "wan": data["sellOutWan"],
        "note": data["sellOutSub"],
    }


def _fmt_cny(yuan: float) -> str:
    return f"¥ {yuan:,.0f}"


def merge_db_sales(data: dict, date_text: str, session) -> dict:
    """用真实数据覆盖 bridge 估算值。

    数据优先级（高 → 低）：
      Sell-In:  dealer_sales 表（vertu 同步）> bridge chart_data（Odoo 实时，已够准）
      Sell-Out: dealer_sales 表（vertu 同步）> walkin_daily_reports 成交额（经销商录入）> bridge 估算
    """
    if not session:
        return data

    from sqlmodel import select
    from app.models.dealer_sales import DealerSales
    from app.models.walkin_daily_report import WalkinDailyReport

    month = date_text[:7]

    # ── 1. dealer_sales 表（sync_from_vertu 写入的 Odoo 数据，最高优先）─────────────
    db_rows = session.exec(
        select(DealerSales).where(DealerSales.check_date.startswith(month))
    ).all()

    has_db_sellout = False
    if db_rows:
        total_in_wan  = sum(r.sell_in_wan  for r in db_rows)
        total_out_wan = sum(r.sell_out_wan for r in db_rows)
        dealer_count  = len({r.dealer_name for r in db_rows})

        if total_in_wan > 0:
            data["sellInWan"]    = round(total_in_wan, 2)
            data["sellInAmount"] = _fmt_cny(total_in_wan * 10000)
            data["sellInSub"]    = f"Odoo同步 · {month} · {dealer_count}家经销商"

        if total_out_wan > 0:
            data["sellOutWan"]    = round(total_out_wan, 2)
            data["sellOutAmount"] = _fmt_cny(total_out_wan * 10000)
            data["sellOutSub"]    = f"Odoo同步 · {month}"
            has_db_sellout = True

    # ── 2. walkin_daily_reports 成交金额（经销商真实录入）────────────────────────────
    # 只要有门店录入了成交额，就用它覆盖 bridge 的估算值（dealer_sales 优先，已设标志）
    if not has_db_sellout:
        walkin_rows = session.exec(
            select(WalkinDailyReport).where(
                WalkinDailyReport.report_date.startswith(month)
            )
        ).all()
        if walkin_rows:
            total_yuan    = sum(r.deal_amount_yuan for r in walkin_rows)
            store_count   = len({r.dealer_id for r in walkin_rows if r.deal_amount_yuan > 0})
            total_walkin  = sum(r.walkin_visits for r in walkin_rows)

            if total_yuan > 0:
                # 真实成交额覆盖估算
                data["sellOutWan"]    = round(total_yuan / 10000, 2)
                data["sellOutAmount"] = _fmt_cny(total_yuan)
                data["sellOutSub"]    = f"门店实录 · {month} · {store_count}家已报"

            if total_walkin > 0:
                # 真实进店数注入（前端可选显示）
                data["realWalkinTotal"] = total_walkin
                data["realWalkinStores"] = len({r.dealer_id for r in walkin_rows})

    return data
