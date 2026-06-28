# -*- coding: utf-8 -*-
"""
导入 2026 年 6 月线下收集的经销商数据到 walkin_daily_reports 表。

数据来源文件（线下收集，已整理）：
  TH (sea03 - VST ECS Thailand):
    - Daily_Sales_Report_Template June (1).xlsx   → 6/18–6/28 Sales Report
    - Daily Store Operation Report-TH.xlsx         → 6/8–6/15  Operation Report
  VN (sea02 - VMG Vietnam):
    - Daily_Sales_Report_Template -VN.xlsx         → 零散天 Sales Report
    - 越南8-12.6xlsx.xlsx                           → 6/8–6/11  Operation Report

  跳过:
    - Daily_Sales_Report_Template 3 (version 1).xlsx  → 无法确认门店
    - Daily_Sales_Report_(2026_June)_TH.xlsx          → 与 template1 日期冲突且数据偏少

字段映射（Sales Report → DB）:
  Walk-ins       → walkin_visits
  Prospects      → prospect_visits
  Appointments   → appointment_visits
  Online         → online_visits
  Referral       → referral_visits
  SA             → sa_visits
  Products Shown → touch_count
  Products Sold  → deal_count
  Revenue        → deal_amount_yuan

字段映射（Operation Report → DB）:
  In-store count       → walkin_visits
  Introduce products   → touch_count
  Touch the product    → use_count
  Place the order      → deal_count
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from sqlmodel import Session, select

from app.database import bootstrap_database, get_engine
from app.models.walkin_daily_report import WalkinDailyReport

# ── 硬编码提取好的数据 ────────────────────────────────────────────────────────
# 格式: (dealer_id, dealer_name, date, walkin, prospect, appt, online, referral, sa,
#         touch, use, deal, revenue, notes)

# TH Sales Report: June 18–28 来自 "Daily_Sales_Report_Template June (1).xlsx"
_TH_SALES = [
    # day: walkin, prospect, appt, online, referral, sa, touch, use, deal, revenue
    (18,  4,  0,  0,  0,  0,  0,  4, 0,  0,      0),
    (19,  6,  0,  1,  0,  0,  0,  5, 0,  1,   5400),
    (20,  7,  0,  1,  2,  0,  0,  6, 0,  0,      0),
    (21, 20,  0,  0,  1,  0,  0, 18, 0,  0,      0),
    (22,  3,  0,  1,  3,  0,  0,  5, 0,  1,  25200),
    (23,  2,  0,  0,  0,  0,  0,  2, 0,  0,   3984),
    (24,  6,  0,  2,  0,  0,  0,  7, 0,  1,   9380),
    (25,  8,  0,  1,  2,  0,  0,  6, 0,  2,  13090),
    (26,  4,  0,  0,  3,  0,  0,  5, 0,  1,      0),
    (27,  3,  0,  1,  1,  0,  0,  3, 0,  1,   8100),
    (28,  1,  0,  0,  0,  0,  0,  1, 0,  0,      0),
]

# TH Operation Report: June 8–15 来自 "Daily Store Operation Report-TH.xlsx"
# 列: (date_day, walkin[in-store], touch[introduce], use[touch_product], deal[place_order])
_TH_OPRT = [
    # day: in-store, introduce(touch), touch_product(use), place_order(deal)
    ( 8, 2, 2, 1, 0),
    ( 9, 1, 1, 3, 0),
    (10, 3, 3, 2, 0),
    (11, 1, 1, 0, 0),
    (12, 0, 0, 0, 0),
    (13, 1, 2, 1, 0),
    (14, 1, 2, 0, 0),
    (15, 5, 4, 4, 0),
]

# VN Sales Report: 零散天 来自 "Daily_Sales_Report_Template -VN.xlsx"
_VN_SALES = [
    # day: walkin, prospect, appt, online, referral, sa, touch, use, deal, revenue
    ( 1,  1,  0,  1,  0,  0,  0,  2, 0,  0,  0),
    ( 4,  1,  0,  0,  0,  0,  0,  1, 0,  0,  0),
    (10,  1,  0,  0,  0,  0,  0,  1, 0,  0,  0),
    (11,  1,  0,  0,  0,  0,  0,  1, 0,  0,  0),
    (14,  2,  0,  0,  0,  0,  0,  2, 0,  0,  0),
    (19,  1,  0,  0,  0,  0,  0,  1, 0,  0,  0),
]

# VN Operation Report: June 8–11 来自 "越南8-12.6xlsx.xlsx"
# June 12 行为空，跳过
_VN_OPRT = [
    # day: in-store, introduce(touch), touch_product(use), place_order(deal)
    ( 8, 6,  6, 6, 0),
    ( 9, 3,  3, 3, 0),
    (10, 5,  5, 5, 0),
    (11, 7,  7, 7, 0),
]

# ── 门店信息 ──────────────────────────────────────────────────────────────────
TH = ("sea03", "VST ECS (Thailand) Co., Ltd.")
VN = ("sea02", "VMG Communication and Technology JSC")

MONTH = "2026-06"


def _to_records() -> list[WalkinDailyReport]:
    records: list[WalkinDailyReport] = []

    # TH Sales Report
    for row in _TH_SALES:
        day, walkin, prospect, appt, online, referral, sa, touch, use, deal, rev = row
        records.append(WalkinDailyReport(
            report_date=f"{MONTH}-{day:02d}",
            dealer_id=TH[0],
            dealer_name=TH[1],
            walkin_visits=walkin,
            prospect_visits=prospect,
            appointment_visits=appt,
            online_visits=online,
            referral_visits=referral,
            sa_visits=sa,
            touch_count=touch,
            use_count=use,
            deal_count=deal,
            deal_amount_yuan=float(rev),
            notes="import:sales_report",
            submitted_by="offline_import",
        ))

    # TH Operation Report
    for row in _TH_OPRT:
        day, instore, introduce, touch_prod, order = row
        if instore == 0 and introduce == 0 and touch_prod == 0 and order == 0:
            continue  # 全零跳过
        records.append(WalkinDailyReport(
            report_date=f"{MONTH}-{day:02d}",
            dealer_id=TH[0],
            dealer_name=TH[1],
            walkin_visits=instore,
            touch_count=introduce,
            use_count=touch_prod,
            deal_count=order,
            notes="import:operation_report",
            submitted_by="offline_import",
        ))

    # VN Sales Report
    for row in _VN_SALES:
        day, walkin, prospect, appt, online, referral, sa, touch, use, deal, rev = row
        records.append(WalkinDailyReport(
            report_date=f"{MONTH}-{day:02d}",
            dealer_id=VN[0],
            dealer_name=VN[1],
            walkin_visits=walkin,
            prospect_visits=prospect,
            appointment_visits=appt,
            online_visits=online,
            referral_visits=referral,
            sa_visits=sa,
            touch_count=touch,
            use_count=use,
            deal_count=deal,
            deal_amount_yuan=float(rev),
            notes="import:sales_report",
            submitted_by="offline_import",
        ))

    # VN Operation Report
    for row in _VN_OPRT:
        day, instore, introduce, touch_prod, order = row
        # VN Sales Report 已经有 day 10 & 11，Operation Report 数字更大（不同口径）
        # 用 notes 区分，两份都写入，reports 对比时可筛选
        records.append(WalkinDailyReport(
            report_date=f"{MONTH}-{day:02d}",
            dealer_id=VN[0],
            dealer_name=VN[1],
            walkin_visits=instore,
            touch_count=introduce,
            use_count=touch_prod,
            deal_count=order,
            notes="import:operation_report",
            submitted_by="offline_import",
        ))

    return records


def main(dry_run: bool = False) -> None:
    bootstrap_database()
    engine = get_engine()

    records = _to_records()
    inserted = 0
    skipped = 0

    with Session(engine) as session:
        for rec in records:
            # 同一门店+日期+来源类型不重复插入
            existing = session.exec(
                select(WalkinDailyReport).where(
                    WalkinDailyReport.dealer_id == rec.dealer_id,
                    WalkinDailyReport.report_date == rec.report_date,
                    WalkinDailyReport.notes == rec.notes,
                )
            ).first()
            if existing:
                skipped += 1
                print(f"  [跳过] {rec.dealer_id} {rec.report_date} ({rec.notes}) 已存在")
                continue

            if not dry_run:
                session.add(rec)
            inserted += 1
            print(f"  [写入] {rec.dealer_id} {rec.report_date} walkin={rec.walkin_visits}"
                  f" deal={rec.deal_count} revenue={rec.deal_amount_yuan} ({rec.notes})")

        if not dry_run:
            session.commit()

    print(f"\n完成：写入 {inserted} 条，跳过 {skipped} 条（已存在）。{'[DRY-RUN 未真实写入]' if dry_run else ''}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
