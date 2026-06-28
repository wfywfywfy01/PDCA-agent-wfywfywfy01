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
    return {"amount": data["sellOutAmount"]}


def _fmt_cny(yuan: float) -> str:
    return f"¥ {yuan:,.0f}"


def merge_db_sales(data: dict, date_text: str, session) -> dict:
    """用 dealer_sales / walkin_daily_reports DB 表覆盖 bridge 返回的 sellin/sellout。

    优先级：dealer_sales（vertu 每日同步） > walkin_daily_reports 成交额（经销商录入）。
    bridge 返回非零时不覆盖，避免内网环境重复叠加。
    """
    if not session:
        return data

    from sqlmodel import select
    from app.models.dealer_sales import DealerSales
    from app.models.walkin_daily_report import WalkinDailyReport

    month = date_text[:7]

    # ── 1. Sell-In / Sell-Out 来自 dealer_sales 表（sync_from_vertu.py 写入）────
    db_rows = session.exec(
        select(DealerSales).where(DealerSales.check_date.startswith(month))
    ).all()

    if db_rows:
        total_in_wan = sum(r.sell_in_wan for r in db_rows)
        total_out_wan = sum(r.sell_out_wan for r in db_rows)
        dealer_count = len({r.dealer_name for r in db_rows})

        # 只在 bridge 没有有效数据时覆盖（bridge 返回 0 或空）
        bridge_sell_in = float(data.get("sellInWan") or 0)
        if total_in_wan > 0 and bridge_sell_in == 0:
            data["sellInWan"] = round(total_in_wan, 2)
            data["sellInAmount"] = _fmt_cny(total_in_wan * 10000)
            data["sellInSub"] = f"DB同步 · {month} · {dealer_count}家经销商"

        bridge_sell_out = float(data.get("sellOutWan") or 0)
        if total_out_wan > 0 and bridge_sell_out == 0:
            data["sellOutWan"] = round(total_out_wan, 2)
            data["sellOutAmount"] = _fmt_cny(total_out_wan * 10000)
            data["sellOutSub"] = f"DB同步 · {month}"

    # ── 2. Sell-Out 兜底：walkin_daily_reports 成交金额（经销商手动录入）─────────
    if not float(data.get("sellOutWan") or 0):
        walkin_rows = session.exec(
            select(WalkinDailyReport).where(
                WalkinDailyReport.report_date.startswith(month)
            )
        ).all()
        if walkin_rows:
            total_yuan = sum(r.deal_amount_yuan for r in walkin_rows)
            if total_yuan > 0:
                data["sellOutWan"] = round(total_yuan / 10000, 2)
                data["sellOutAmount"] = _fmt_cny(total_yuan)
                data["sellOutSub"] = f"门店录入 · {month}"

    return data
