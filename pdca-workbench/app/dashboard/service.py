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


def merge_db_sales(data: dict, date_text: str, session, user=None) -> dict:
    """Use authoritative database rows to override legacy-source values.

    数据优先级（高 → 低）：
      Sell-In/Sell-Out: dealer_sales 表（vertu 同步）> bridge 的真实 Odoo 行；
      缺失时保持缺失，不用五件套 USD 或比例推算填充 CNY KPI。
    """
    if not session:
        return data

    from sqlmodel import select
    from app.models.dealer_sales import DealerSales
    from app.models.walkin_daily_report import WalkinDailyReport
    from app.auth.scope import visible_dealer_names, visible_store_ids

    month = date_text[:7]

    # ── 1. dealer_sales 表（sync_from_vertu 写入的 Odoo 数据，最高优先）─────────────
    dealer_stmt = select(DealerSales).where(DealerSales.check_date.startswith(month))
    names = visible_dealer_names(user, session) if user is not None else None
    store_ids = visible_store_ids(user, session) if user is not None else None
    if names is not None:
        db_rows = (
            session.exec(dealer_stmt.where(DealerSales.dealer_name.in_(names))).all()
            if names else []
        )
    else:
        db_rows = session.exec(dealer_stmt).all()

    if db_rows:
        total_in_wan  = sum(r.sell_in_wan  for r in db_rows)
        total_out_wan = sum(r.sell_out_wan for r in db_rows)
        dealer_count  = len({r.dealer_name for r in db_rows})

        # A successful source row whose value is zero is a real zero, not a
        # missing value.  Always override legacy/derived values when rows exist.
        data["sellInWan"] = round(total_in_wan, 2)
        data["sellInAmount"] = _fmt_cny(total_in_wan * 10000)
        data["sellInSub"] = f"Odoo同步 · {month} · {dealer_count}家经销商"
        data["sellOutWan"] = round(total_out_wan, 2)
        data["sellOutAmount"] = _fmt_cny(total_out_wan * 10000)
        data["sellOutSub"] = f"Odoo同步 · {month} · {dealer_count}家经销商"
        data.setdefault("dataState", {}).update({"sellIn": "live", "sellOut": "live"})
        data.setdefault("dataSource", {}).update({"sellIn": "dealer_sales_db", "sellOut": "dealer_sales_db"})

    # ── 2. walkin_daily_reports（经销商真实录入，USD 与客流口径）────────────────────
    walkin_stmt = select(WalkinDailyReport).where(
        WalkinDailyReport.report_date.startswith(month)
    )
    if store_ids is not None:
        walkin_rows = (
            session.exec(walkin_stmt.where(WalkinDailyReport.dealer_id.in_(store_ids))).all()
            if store_ids else []
        )
    else:
        walkin_rows = session.exec(walkin_stmt).all()
    if walkin_rows:
        total_walkin = sum(r.total_visits for r in walkin_rows)
        data["realWalkinTotal"] = total_walkin
        data["realWalkinStores"] = len({r.dealer_id for r in walkin_rows})
        # Five-kit revenue is reported in USD.  It must never overwrite the
        # CNY Sell-out KPI merely because the legacy field name contains yuan.
        data["reportedRevenueUsd"] = round(sum(r.deal_amount_yuan for r in walkin_rows), 2)

    return data
