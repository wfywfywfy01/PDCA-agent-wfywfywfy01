# -*- coding: utf-8 -*-
"""每日经营日报（P5+）：生产容器内定时生成，DB 事实源 → VPS IM 群。

与 scripts/daily_report_push.py（部署机手工版）逻辑一致，但使用应用
自身的数据库引擎，不依赖部署机网络。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.database import get_engine
from app.models.dealer_sales import DealerSales
from app.models.dealer_store import DealerStore
from app.models.logistics import LogisticsShipment
from app.models.meeting import MeetingRecord
from app.models.pdca_task import PdcaTask
from app.models.walkin_daily_report import WalkinDailyReport


def _fmt_money(wan: float | None) -> str:
    if wan is None:
        return "N/A"
    return f"{wan:,.2f} 万"


def _snapshot_total(rows: list[DealerSales]) -> float | None:
    if not rows:
        return None
    return round(sum(float(row.sell_in_wan or 0) for row in rows), 2)


def _fmt_synced_at(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return utc_value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def _is_test_store(store: DealerStore) -> bool:
    store_id = (store.store_id or "").strip().lower()
    name = (store.name or "").strip().lower()
    return store_id.startswith(("qa-", "test-", "demo-")) or any(
        marker in name for marker in ("测试", "演示", "demo")
    )


def build_report(day: str) -> str:
    month = day[:7]
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    day_before_yesterday = (date.fromisoformat(day) - timedelta(days=2)).isoformat()

    with Session(get_engine()) as session:
        # dealer_sales 每日保存月累计快照。月累计只取最新快照，昨日新增取相邻快照差额。
        sales_rows = session.exec(
            select(DealerSales).where(
                DealerSales.check_date.startswith(month),
                DealerSales.check_date <= day,
            )
        ).all()
        rows_by_date: dict[str, list[DealerSales]] = {}
        for row in sales_rows:
            rows_by_date.setdefault(row.check_date, []).append(row)
        latest_date = max(rows_by_date, default=None)
        latest_rows = rows_by_date.get(latest_date, []) if latest_date else []
        mtd_wan = _snapshot_total(latest_rows)
        yesterday_total = _snapshot_total(rows_by_date.get(yesterday, []))
        prior_total = _snapshot_total(rows_by_date.get(day_before_yesterday, []))
        yesterday_wan = (
            round(yesterday_total - prior_total, 2)
            if yesterday_total is not None and prior_total is not None
            else None
        )

        # 全部真实活跃门店都应上报；测试门店不进入经营指标。
        stores = [
            store
            for store in session.exec(
            select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
            ).all()
            if not _is_test_store(store)
        ]
        total_stores = len(stores)
        eligible_store_ids = {store.store_id for store in stores}
        reported_ids = eligible_store_ids & {
            row.dealer_id
            for row in session.exec(
                select(WalkinDailyReport).where(WalkinDailyReport.report_date == yesterday)
            ).all()
        }
        missing_names = [
            store.name for store in stores if store.store_id not in reported_ids
        ]

        # 物流：近 7 天在途/异常（复用 logistics/service 的统一判定，评审整改）
        from app.logistics.service import _judge_status, _load_settings, _status_is_delivered

        week_ago = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
        logistics_rows = session.exec(
            select(LogisticsShipment).where(LogisticsShipment.record_date >= week_ago)
        ).all()
        transit = abnormal = 0
        settings_cfg = _load_settings()
        for row in logistics_rows:
            row_dict = {
                "current_status": row.current_status or "",
                "status": row.current_status or "",
                "ship_date": row.ship_date or day,
            }
            judgement, _reason, _progress = _judge_status(row_dict, settings_cfg, day)
            if judgement == "异常":
                abnormal += 1
                continue
            if _status_is_delivered(row_dict):
                continue
            transit += 1

        all_meetings = session.exec(select(MeetingRecord)).all()
        latest_meeting_sync = max(
            (row.synced_at for row in all_meetings if row.synced_at), default=None
        )
        meeting_fresh = False
        if latest_meeting_sync:
            sync_utc = (
                latest_meeting_sync.replace(tzinfo=timezone.utc)
                if latest_meeting_sync.tzinfo is None
                else latest_meeting_sync
            )
            meeting_fresh = sync_utc.astimezone(ZoneInfo("Asia/Shanghai")).date() >= (
                date.fromisoformat(day) - timedelta(days=1)
            )
        meetings = sum(1 for row in all_meetings if row.meeting_date == day)
        from app.statuses import is_done

        task_rows = session.exec(select(PdcaTask)).all()
        today_tasks = sum(
            1 for row in task_rows if row.task_date == day and not is_done(row.status)
        )
        overdue_tasks = sum(
            1 for row in task_rows if row.task_date < day and not is_done(row.status)
        )

        synced = max((row.synced_at for row in latest_rows if row.synced_at), default=None)

    lines = [
        f"📊 PDCA 经营日报 {day}",
        "",
        "【业绩】",
        f"· 昨日新增 Sell-in（{yesterday[5:]}）：{_fmt_money(yesterday_wan)}",
        f"· 本月累计 Sell-in：{_fmt_money(mtd_wan)}",
        "",
    ]
    if not total_stores:
        lines += [f"【门店五件套（{yesterday[5:]}）】N/A", "· 未配置有效填报门店"]
    elif missing_names:
        lines.append(f"【门店五件套（{yesterday[5:]}）】{len(reported_ids)}/{total_stores} 家已上报")
        lines.append("· 缺报：" + "、".join(missing_names[:5])
                     + ("…" if len(missing_names) > 5 else ""))
        lines.append("· 零客流也要如实上报，不能把 0 当成未上报")
    else:
        lines += [f"【门店五件套（{yesterday[5:]}）】{total_stores}/{total_stores} 家已上报", "· 全部上报完成 ✓"]
    logistics_text = (
        f"近 7 天在途 {transit} 单 · 异常 {abnormal} 单"
        if logistics_rows
        else "N/A（无近期可验证数据）"
    )
    meeting_text = f"今日 {meetings} 场" if meeting_fresh else "N/A（数据未更新）"
    task_text = (
        f"今日 {today_tasks} 项 · 逾期 {overdue_tasks} 项"
        if task_rows
        else "N/A"
    )
    lines += [
        "",
        f"【物流】{logistics_text}",
        f"【会议】{meeting_text} · 【待办】{task_text}",
        "",
        f"数据截至：{_fmt_synced_at(synced)}",
        "入口：https://pdca-workbench-teams.vertu.cn/app/",
    ]
    return "\n".join(lines)
