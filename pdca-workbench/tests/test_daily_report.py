# -*- coding: utf-8 -*-
"""app.daily_report 单测。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.daily_report import build_report
from app.models.dealer_store import DealerStore
from app.models.logistics import LogisticsShipment
from app.models.walkin_daily_report import WalkinDailyReport


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'}")
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch("app.daily_report.get_engine", return_value=self.engine)
        self.sales_patch = patch(
            "app.daily_report._fetch_live_sales",
            return_value=(
                {
                    "state": "live",
                    "wan": 22.88,
                    "quantity": 16,
                    "as_of": "2026-08-30T08:30:01+08:00",
                },
                {
                    "state": "live",
                    "wan": 700.80,
                    "quantity": 636,
                    "as_of": "2026-08-30T08:30:02+08:00",
                },
            ),
        )
        self.target_patch = patch(
            "app.daily_report.fetch_dept_monthly_target",
            return_value=8_050_000.0,  # 三部全月目标 805 万（元）
        )
        self.engine_patch.start()
        self.sales_patch.start()
        self.target_patch.start()

    def tearDown(self):
        self.target_patch.stop()
        self.sales_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_report_uses_live_sales_and_does_not_invent_completion_rate(self):
        with Session(self.engine) as session:
            session.add(WalkinDailyReport(report_date="2026-08-29", dealer_id="s1", dealer_name="店一"))
            session.add(WalkinDailyReport(report_date="2026-08-29", dealer_id="qa-test", dealer_name="测试店"))
            session.commit()

        text = build_report("2026-08-30")

        self.assertIn("昨日（08-29）：22.88 万 · 16 台", text)
        self.assertIn("本月累计：700.80 万 · 636 台", text)
        self.assertIn("目标 805.0 万 · 实际 700.80 万 · 完成率 87.1%", text)
        self.assertIn("时间进度 96.8% · 落后 9.7 个百分点", text)
        self.assertIn("系统收到 0 家必报门店填报", text)
        self.assertIn("应报 8 家", text)
        self.assertIn("缺报 8 家", text)
        self.assertIn("Luxem Store", text)
        self.assertIn("reStore", text)
        self.assertIn("【物流】近 7 天在途 0 单 · 异常 0 单", text)
        self.assertNotIn("4.41 万", text)
        self.assertNotIn("/44", text)
        self.assertNotIn("会议", text)
        self.assertNotIn("待办", text)

    def test_missing_list_respects_required_stores_and_logistics_transit(self):
        with Session(self.engine) as session:
            session.add(DealerStore(store_id="me003", name="Billionaire Collections"))
            session.add(WalkinDailyReport(
                report_date="2026-08-29", dealer_id="me003", dealer_name="Billionaire Collections",
            ))
            session.add(LogisticsShipment(
                record_date="2026-08-28", tracking_number="T1", carrier="DHL",
                customer="x", current_status="运输中", ship_date="2026-08-28", progress_pct=50,
            ))
            session.add(LogisticsShipment(
                record_date="2026-08-28", tracking_number="T2", carrier="DHL",
                customer="x", current_status="已签收", ship_date="2026-08-28", progress_pct=100,
            ))
            session.commit()

        text = build_report("2026-08-30")

        self.assertIn("系统收到 1 家必报门店填报", text)
        self.assertIn("应报 8 家", text)
        self.assertIn("缺报 7 家", text)
        self.assertIn("Luxem Store", text)
        self.assertNotIn("Billionaire Collections", text)
        self.assertIn("【物流】近 7 天在途 1 单 · 异常 0 单", text)

    def test_target_query_failure_omits_section(self):
        with patch("app.daily_report.fetch_dept_monthly_target", side_effect=RuntimeError("boom")):
            text = build_report("2026-08-30")

        self.assertNotIn("业绩目标", text)
        self.assertIn("系统收到 0 家必报门店填报", text)
        self.assertIn("【物流】", text)

    def test_non_live_sales_fails_closed(self):
        with patch(
            "app.daily_report._fetch_live_sales",
            return_value=({"state": "stale"}, {"state": "live", "wan": 1, "quantity": 1}),
        ):
            with self.assertRaisesRegex(RuntimeError, "不是实时状态"):
                build_report("2026-08-30")


class TargetValidationTests(unittest.TestCase):
    def test_incomplete_department_target_fails_closed(self):
        from app.vertu.sales import _dept_target_async

        async def fake_target(args, timeout):
            department = args[args.index("--dept-l2") + 1]
            if department == "经销商一部":
                return {"rows": [{"target_amount": 100_000}]}
            return {"rows": [{"target_amount": None}]}

        with patch.dict(os.environ, {
            "PDCA_VERTU_SELLIN_DEPARTMENTS": "经销商一部,经销商二部",
            "PDCA_VERTU_DEPT_L1": "海外渠道",
        }), patch("app.vertu.sales.run_vertu_json", side_effect=fake_target):
            with self.assertRaisesRegex(RuntimeError, "目标数据不完整"):
                asyncio.run(_dept_target_async("2026-08-01", "2026-08-31"))


class DailyReportJobTests(unittest.TestCase):
    def test_generation_failure_only_uses_alert_channel(self):
        from app.scheduler.jobs import daily_report_job

        with patch("app.daily_report.build_report", side_effect=RuntimeError("upstream failed")), \
                patch("app.vps_im_push.push_vps_message") as business_push, \
                patch("app.scheduler.run_ledger.claim_run", return_value=True), \
                patch("app.scheduler.run_ledger.finish_run") as finish_run, \
                patch("app.scheduler.jobs.notify") as notify:
            daily_report_job()

        business_push.assert_not_called()
        finish_run.assert_called_once()
        notify.assert_called_once()

    def test_same_day_duplicate_does_not_build_or_send(self):
        from app.scheduler.jobs import daily_report_job

        with patch("app.scheduler.run_ledger.claim_run", return_value=False), \
                patch("app.daily_report.build_report") as build_report, \
                patch("app.vps_im_push.push_vps_message") as business_push:
            daily_report_job()
        build_report.assert_not_called()
        business_push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
