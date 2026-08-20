# -*- coding: utf-8 -*-
"""每日经营日报（P5+）：生产容器内定时生成，DB 事实源 → VPS IM 群。

与 scripts/daily_report_push.py（部署机手工版）逻辑一致，但使用应用
自身的数据库引擎，不依赖部署机网络。
"""
from __future__ import annotations

from datetime import date, timedelta

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
        return "—"
    return f"{wan:,.2f} 万"


def build_report(day: str) -> str:
    month = day[:7]
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()

    with Session(get_engine()) as session:
        # 昨日/本月 Sell-in（榜单口径：仅正向业绩）
        yesterday_rows = session.exec(
            select(DealerSales).where(DealerSales.check_date == yesterday)
        ).all()
        yesterday_wan = round(
            sum(r.sell_in_wan for r in yesterday_rows if r.sell_in_wan > 0), 2
        )
        mtd_rows = session.exec(
            select(DealerSales).where(DealerSales.check_date.startswith(month))
        ).all()
        mtd_wan = round(sum(r.sell_in_wan for r in mtd_rows if r.sell_in_wan > 0), 2)

        # 五件套上报进度 + 缺报名单
        stores = session.exec(
            select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
        ).all()
        total_stores = len(stores)
        reported_ids = {
            row.dealer_id
            for row in session.exec(
                select(WalkinDailyReport).where(WalkinDailyReport.report_date == day)
            ).all()
        }
        missing_names = [
            store.name for store in stores if store.store_id not in reported_ids
        ]

        # 物流：近 7 天在途/异常（简单关键词判定，与看板一致）
        week_ago = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
        logistics_rows = session.exec(
            select(LogisticsShipment).where(LogisticsShipment.record_date >= week_ago)
        ).all()
        transit = abnormal = 0
        for row in logistics_rows:
            status = (row.current_status or "").lower()
            if "异常" in status or "清关失败" in status:
                abnormal += 1
                continue
            if "delivered" in status or "已签收" in status:
                continue
            transit += 1

        meetings = len(
            session.exec(
                select(MeetingRecord).where(MeetingRecord.meeting_date == day)
            ).all()
        )
        done_statuses = ("done", "completed", "complete", "已完成")
        pending_tasks = len(
            [
                row
                for row in session.exec(
                    select(PdcaTask).where(PdcaTask.task_date == day)
                ).all()
                if (row.status or "").strip().lower() not in done_statuses
            ]
        )

        synced = None
        for row in mtd_rows:
            if row.synced_at and (synced is None or row.synced_at > synced):
                synced = row.synced_at

    lines = [
        f"📊 PDCA 经营日报 {day}",
        "",
        "【业绩】",
        f"· 昨日 Sell-in：{_fmt_money(yesterday_wan)}",
        f"· 本月 Sell-in：{_fmt_money(mtd_wan)}",
        "",
        f"【门店五件套】{len(reported_ids)}/{total_stores} 家已上报",
    ]
    if missing_names:
        lines.append("· 缺报：" + "、".join(missing_names[:5])
                     + ("…" if len(missing_names) > 5 else ""))
        lines.append("· 零客流也要如实上报，不能把 0 当成未上报")
    else:
        lines.append("· 全部上报完成 ✓")
    lines += [
        "",
        f"【物流】近 7 天在途 {transit} 单 · 异常 {abnormal} 单",
        f"【会议】今日 {meetings} 场 · 【待办】{pending_tasks} 项未完成",
        "",
        f"数据截至：{str(synced)[:16] if synced else '尚未同步'}",
        "入口：https://pdca-workbench-teams.vertu.cn/app/",
    ]
    return "\n".join(lines)
