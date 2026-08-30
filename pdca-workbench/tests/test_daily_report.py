# -*- coding: utf-8 -*-
"""app.daily_report 单测（服务器内日报生成）。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.daily_report import build_report
from app.models.dealer_sales import DealerSales
from app.models.dealer_store import DealerStore
from app.models.meeting import MeetingRecord
from app.models.pdca_task import PdcaTask
from app.models.walkin_daily_report import WalkinDailyReport


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'}"
        )
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.daily_report.get_engine", return_value=self.engine)
        self.patch_engine.start()

    def tearDown(self):
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self):
        with Session(self.engine) as session:
            session.add(DealerSales(check_date="2026-08-18", dealer_name="A", sell_in_wan=80.0, units=8))
            session.add(DealerSales(check_date="2026-08-18", dealer_name="B", sell_in_wan=-1.0, units=-1))
            session.add(DealerSales(check_date="2026-08-19", dealer_name="A", sell_in_wan=100.0, units=10))
            session.add(DealerSales(check_date="2026-08-19", dealer_name="B", sell_in_wan=-2.0, units=-1))
            session.add(DealerSales(
                check_date="2026-08-20", dealer_name="A", sell_in_wan=105.0, units=11,
                synced_at=datetime(2026, 8, 20, 0, 30),
            ))
            session.add(DealerSales(
                check_date="2026-08-20", dealer_name="B", sell_in_wan=-3.0, units=-1,
                synced_at=datetime(2026, 8, 20, 0, 30),
            ))
            session.add(DealerStore(store_id="s1", name="店一", region="中东", country="沙特", dealer_level="L1", is_active=True))
            session.add(DealerStore(store_id="s2", name="店二", region="欧洲", country="俄", dealer_level="L1", is_active=True))
            session.add(DealerStore(store_id="qa-test", name="QA测试门店", is_active=True))
            session.add(WalkinDailyReport(report_date="2026-08-19", dealer_id="s1", dealer_name="店一", walkin_visits=3))
            session.add(MeetingRecord(meeting_date="2026-08-20", external_id="m1", title="周会"))
            session.add(PdcaTask(task_date="2026-08-19", title="逾期待办", status="pending"))
            session.add(PdcaTask(task_date="2026-08-20", title="今日待办", status="pending"))
            session.add(PdcaTask(task_date="2026-08-20", title="已完成", status="done"))
            session.commit()

    def test_report_uses_snapshot_delta_previous_day_and_real_active_stores(self):
        self._seed()
        text = build_report("2026-08-20")
        self.assertIn("PDCA 经营日报 2026-08-20", text)
        self.assertIn("昨日新增 Sell-in（08-19）：19.00 万", text)
        self.assertIn("本月累计 Sell-in：102.00 万", text)
        self.assertIn("1/2 家已上报", text)
        self.assertIn("缺报：店二", text)
        self.assertIn("会议】今日 1 场", text)
        self.assertIn("待办】今日 1 项 · 逾期 1 项", text)
        self.assertIn("数据截至：2026-08-20 08:30", text)
        self.assertNotIn("QA测试门店", text)

    def test_empty_db_does_not_crash(self):
        text = build_report("2026-08-20")
        self.assertIn("昨日新增 Sell-in（08-19）：N/A", text)
        self.assertIn("本月累计 Sell-in：N/A", text)
        self.assertIn("门店五件套（08-19）】N/A", text)
        self.assertIn("物流】N/A", text)
        self.assertIn("会议】N/A", text)


if __name__ == "__main__":
    unittest.main()
