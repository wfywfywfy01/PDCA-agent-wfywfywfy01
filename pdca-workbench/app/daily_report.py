# -*- coding: utf-8 -*-
"""每日经营日报：只发布可直接验证的核心数据。"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.database import get_engine
from app.models.walkin_daily_report import WalkinDailyReport, latest_walkin_reports
from app.models.dealer_store import DealerStore, is_demo_store
from app.models.logistics import LogisticsShipment
from app.vertu.sales import fetch_sell_in

# 业务确认的每日必报五件套门店清单（store_id → 名称兜底；展示名以门店主数据为准）
REQUIRED_FIVE_KIT_STORES: dict[str, str] = {
    "me003": "Billionaire Collections",
    "me007": "Luxem Store",
    "eu001": "Optimizers d.o.o.",
    "eu002": "Robo Trading Ltd",
    "eu003": "VERTU LONDON LTD",
    "sea03": "VST ECS (Thailand) Co., Ltd. · Siam Paragon",
    "ca004": "LLC TC Azimut",
    "ca006": "reStore",
}


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
        value = datetime.fromisoformat(latest)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return "N/A"


def build_report(day: str) -> str:
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    week_ago = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    sales = _fetch_live_sales(yesterday, day)
    yesterday_wan, yesterday_units = _validated_sales(sales[0], "昨日")
    month_wan, month_units = _validated_sales(sales[1], "本月")

    with Session(get_engine()) as session:
        reports = latest_walkin_reports(session.exec(
            select(WalkinDailyReport).where(WalkinDailyReport.report_date == yesterday)
        ).all())
        required_stores = session.exec(
            select(DealerStore).where(DealerStore.store_id.in_(REQUIRED_FIVE_KIT_STORES))
        ).all()
        logistics_rows = session.exec(
            select(LogisticsShipment).where(LogisticsShipment.record_date >= week_ago)
        ).all()

    reported_ids = {
        row.dealer_id
        for row in reports
        if row.dealer_id
        and not is_demo_store(row.dealer_id, row.dealer_name)
    }

    name_by_id = {store.store_id: store.name for store in required_stores}
    for sid, fallback_name in REQUIRED_FIVE_KIT_STORES.items():
        name_by_id.setdefault(sid, fallback_name)
    missing_ids = [sid for sid in REQUIRED_FIVE_KIT_STORES if sid not in reported_ids]
    missing_names = [name_by_id[sid] for sid in missing_ids]

    # 物流：近 7 天在途/异常（复用物流服务的统一判定）
    from app.logistics.service import _is_delivered, _judge_status, _load_settings

    transit = abnormal = 0
    settings_cfg = _load_settings()
    for row in logistics_rows:
        row_dict = {
            "current_status": row.current_status or "",
            "status": row.current_status or "",
            "ship_date": row.ship_date or day,
            "progress_pct": row.progress_pct,
        }
        judgement, _reason, _progress = _judge_status(row_dict, settings_cfg, day)
        if judgement == "异常":
            abnormal += 1
            continue
        if _is_delivered(row_dict):
            continue
        transit += 1

    five_kit_lines = [
        f"【门店五件套回执（{yesterday[5:]}）】",
        f"· 系统收到 {len(reported_ids)} 家门店填报",
        f"· 应报 {len(REQUIRED_FIVE_KIT_STORES)} 家",
    ]
    if missing_ids:
        five_kit_lines.append(f"· 缺报 {len(missing_ids)} 家：{'、'.join(missing_names)}")
    else:
        five_kit_lines.append("· 应报门店已全部上报 ✅")

    return "\n".join(
        [
            f"📊 PDCA 核心日报 {day}",
            "",
            "【Sell-in｜Vertu 实时查询】",
            f"· 昨日（{yesterday[5:]}）：{yesterday_wan:,.2f} 万 · {yesterday_units} 台",
            f"· 本月累计：{month_wan:,.2f} 万 · {month_units} 台",
            "",
            *five_kit_lines,
            "",
            f"【物流】近 7 天在途 {transit} 单 · 异常 {abnormal} 单",
            "",
            f"数据截至：{_as_of(sales)}",
            "入口：https://pdca-workbench-teams.vertu.cn/app/",
        ]
    )
