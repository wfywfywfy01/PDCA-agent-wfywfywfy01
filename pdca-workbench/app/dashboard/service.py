# -*- coding: utf-8 -*-
"""Dashboard 业务服务（委托遗留实现）。"""
from __future__ import annotations

from app.config import get_settings
from app.legacy import bridge


def overview(date_text: str, period: str = "day", session_user: dict | None = None) -> dict:
    return bridge.api_dashboard_overview(date_text, period, session_user=session_user)


def workbench_overview(
    date_text: str,
    period: str = "day",
    session_user: dict | None = None,
) -> dict:
    """Build the initial workbench payload without remote identity/IM calls.

    The authenticated session is the authority for the visible user identity.
    Sales facts are merged from the scoped database by ``merge_db_sales`` and
    the dedicated live Sell-in endpoint refreshes the unrestricted KPI.
    """
    user = session_user or {}
    role = str(user.get("role") or "viewer").strip().lower()
    role_labels = {
        "admin": "系统管理员",
        "manager": "海外中台主管",
        "sales": "经销商销售",
        "dealer": "经销商门店",
        "viewer": "只读访客",
    }
    period_labels = {
        "day": "日",
        "week": "周",
        "month": "月",
        "quarter": "季",
    }
    name = str(
        user.get("display_name")
        or user.get("sales_name")
        or user.get("username")
        or "工作台用户"
    ).strip()
    return {
        "managerName": name,
        "managerRole": f"{role_labels.get(role, role or '工作台用户')} · {period_labels.get(period, '日')}视图 · {date_text}",
        "sellInAmount": "—",
        "sellInWan": None,
        "sellOutAmount": "—",
        "sellOutWan": None,
        "sellInSub": "尚未同步业绩数据",
        "sellOutSub": "尚未同步终销数据",
        "agentScore": None,
        "scoreComment": "AI 评分未接入可验证证据源，暂不计算（未接入，非数据缺失）",
        "dataState": {
            "sellIn": "missing",
            "sellOut": "missing",
            "agentScore": "missing",
        },
        "dataSource": {
            "sellIn": "missing",
            "sellOut": "missing",
        },
    }


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


def db_sellin_summary(month: str, session, user=None) -> dict:
    """P1：从 dealer_sales 表聚合经销商进货汇总（替代 bridge 读 data_raw JSON）。

    返回结构与 /api/dealer/sellin-summary 一致：{month, total_wan, dealers,
    has_data, trend}。受限账号按 scope 经销商名过滤（与调用方后过滤一致）。
    """
    from sqlmodel import select
    from app.models.dealer_sales import DealerSales
    from app.auth.scope import resolve_data_scope, scoped_active_dealer_names

    names = None
    if user is not None and not resolve_data_scope(user, session).unrestricted:
        names = scoped_active_dealer_names(user, session)

    def _month_rows(mo: str) -> list:
        stmt = select(DealerSales).where(DealerSales.check_date.startswith(mo))
        if names is not None:
            stmt = stmt.where(DealerSales.dealer_name.in_(names))
        return list(session.exec(stmt).all())

    rows = _month_rows(month)
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(
            row.dealer_name,
            {"name": row.dealer_name, "wan": 0.0, "quantity": 0},
        )
        item["wan"] += float(row.sell_in_wan or 0)
        item["quantity"] += int(row.units or 0)
    dealers = [
        {"name": item["name"], "wan": round(item["wan"], 2), "quantity": item["quantity"]}
        for item in grouped.values()
        if item["wan"] > 0 or item["quantity"] > 0
    ]
    dealers.sort(key=lambda item: item["wan"], reverse=True)
    for index, dealer in enumerate(dealers):
        dealer["rank"] = index + 1

    trend = []
    year, number = int(month[:4]), int(month[5:7])
    for offset in range(5, -1, -1):
        current = number - offset
        current_year = year
        while current <= 0:
            current += 12
            current_year -= 1
        mo = f"{current_year:04d}-{current:02d}"
        mo_total = round(sum(float(row.sell_in_wan or 0) for row in _month_rows(mo)), 2)
        trend.append({"month": mo, "wan": mo_total})

    return {
        "month": month,
        "total_wan": round(sum(item["wan"] for item in dealers), 2),
        "dealers": dealers,
        "has_data": bool(dealers),
        "trend": trend,
        "source": "dealer_sales_db",
    }


def db_customer_center_summary(session, user=None) -> list[dict] | None:
    """P5：客户分层概览改由 customer_profiles 表聚合（替代 bridge 读文件）。

    返回 [{"level": "A", "total": n, "touched": None, "target": 0}, ...]；
    库内无客户时返回 None，调用方回退 bridge（CSV 文件兜底）。
    touched 尚无触达记录数据源，显式 None → 前端显示"未同步"（数据诚实）。
    """
    from sqlmodel import select

    from app.auth.scope import resolve_data_scope
    from app.models.customer_profile import CustomerProfile

    rows = list(session.exec(select(CustomerProfile)).all())
    if not rows:
        return None
    rows = [row.model_dump() for row in rows]
    if user is not None:
        scope = resolve_data_scope(user, session)
        if not scope.unrestricted:
            from app.auth.scope import filter_rows_by_scope

            rows = filter_rows_by_scope(
                rows,
                owner_keys=scope.owner_keys,
                dealer_names=scope.dealer_names,
            )
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for row in rows:
        grade = (row.get("abcd_grade") or "").strip().upper()
        if grade not in counts:
            grade = "D"
        counts[grade] += 1
    return [
        {"level": grade, "total": counts[grade], "touched": None, "target": 0}
        for grade in ("A", "B", "C", "D")
        if counts[grade]
    ]


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
    from app.auth.scope import resolve_data_scope, scoped_active_dealer_names, scoped_active_store_ids

    month = date_text[:7]

    # ── 1. dealer_sales 表（sync_from_vertu 写入的 Odoo 数据，最高优先）─────────────
    dealer_stmt = select(DealerSales).where(DealerSales.check_date.startswith(month))
    # store_ids 无论是否 unrestricted 都需要（walkin 汇总用到），提前解析。
    store_ids = scoped_active_store_ids(user, session) if user is not None else []
    # VPS ``sales +orders`` 返回的客户名已脱敏（如 "未知客户"/"H*****"），无法按名称
    # 匹配门店主数据。管理员（unrestricted）直接汇总全量；受限账号仍按名称过滤。
    if user is not None and resolve_data_scope(user, session).unrestricted:
        db_rows = list(session.exec(dealer_stmt).all())
    else:
        names = scoped_active_dealer_names(user, session) if user is not None else []
        db_rows = (
            session.exec(dealer_stmt.where(DealerSales.dealer_name.in_(names))).all()
            if names else []
        )

    if db_rows:
        total_in_wan  = sum(r.sell_in_wan  for r in db_rows)
        total_out_wan = sum(r.sell_out_wan for r in db_rows)
        dealer_count  = len({r.dealer_name for r in db_rows})
        batch_date = max((r.check_date for r in db_rows if r.check_date), default=month)
        synced_at = max((r.synced_at for r in db_rows if r.synced_at), default=None)
        if synced_at is not None:
            data["dataAsOf"] = synced_at.isoformat(timespec="seconds")

        # A successful source row whose value is zero is a real zero, not a
        # missing value.  Always override legacy/derived values when rows exist.
        data["sellInWan"] = round(total_in_wan, 2)
        data["sellInAmount"] = _fmt_cny(total_in_wan * 10000)
        data["sellInSub"] = f"Odoo同步 · 批次 {batch_date} · {dealer_count}家经销商"
        data["sellOutWan"] = round(total_out_wan, 2)
        data["sellOutAmount"] = _fmt_cny(total_out_wan * 10000)
        data["sellOutSub"] = f"Odoo同步 · 批次 {batch_date} · {dealer_count}家经销商"
        data.setdefault("dataState", {}).update({"sellIn": "live", "sellOut": "live"})
        data.setdefault("dataSource", {}).update({"sellIn": "dealer_sales_db", "sellOut": "dealer_sales_db"})

    # ── 2. walkin_daily_reports（经销商真实录入，USD 与客流口径）────────────────────
    walkin_stmt = select(WalkinDailyReport).where(
        WalkinDailyReport.report_date.startswith(month)
    )
    walkin_rows = (
        session.exec(walkin_stmt.where(WalkinDailyReport.dealer_id.in_(store_ids))).all()
        if store_ids else []
    )
    if walkin_rows:
        total_walkin = sum(r.total_visits for r in walkin_rows)
        data["realWalkinTotal"] = total_walkin
        data["realWalkinStores"] = len({r.dealer_id for r in walkin_rows})
        # Five-kit revenue is reported in USD.  It must never overwrite the
        # CNY Sell-out KPI merely because the legacy field name contains yuan.
        settings = get_settings()
        review_threshold = min(
            settings.max_reported_revenue_usd,
            getattr(settings, "revenue_review_threshold_usd", settings.max_reported_revenue_usd),
        )
        valid_revenue = [r.deal_amount_yuan for r in walkin_rows if r.deal_amount_yuan <= review_threshold]
        data["reportedRevenueUsd"] = round(sum(valid_revenue), 2)
        data["reportedRevenueReviewCount"] = len(walkin_rows) - len(valid_revenue)
        # 终销（Sell-out）口径为 USD（门店五件套上报），不是 CNY 万。用独立字段表达，
        # 供前端 Sell-out 卡片直接展示；不再复用 dealer_sales.sell_out_wan（该列已清空）。
        store_count = len({r.dealer_id for r in walkin_rows})
        data["sellOutUsd"] = round(sum(valid_revenue), 2)
        data["sellOutSub"] = f"门店五件套上报 · {store_count} 家门店 · USD"
        data.setdefault("dataState", {}).update({"sellOut": "live"})
        data.setdefault("dataSource", {}).update({"sellOut": "five_kit_db"})

    return data
