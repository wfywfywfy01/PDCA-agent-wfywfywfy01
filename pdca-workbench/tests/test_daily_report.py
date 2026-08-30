# -*- coding: utf-8 -*-
"""app.daily_report 单测。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.daily_report import build_report
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
        self.engine_patch.start()
        self.sales_patch.start()

    def tearDown(self):
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
        self.assertIn("系统收到 1 家门店填报", text)
        self.assertIn("应报门店清单尚未确认", text)
        self.assertNotIn("4.41 万", text)
        self.assertNotIn("/44", text)
        self.assertNotIn("物流", text)
        self.assertNotIn("会议", text)
        self.assertNotIn("待办", text)

    def test_non_live_sales_fails_closed(self):
        with patch(
            "app.daily_report._fetch_live_sales",
            return_value=({"state": "stale"}, {"state": "live", "wan": 1, "quantity": 1}),
        ):
            with self.assertRaisesRegex(RuntimeError, "不是实时状态"):
                build_report("2026-08-30")


if __name__ == "__main__":
    unittest.main()
