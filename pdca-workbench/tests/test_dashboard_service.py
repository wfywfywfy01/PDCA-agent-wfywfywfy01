# -*- coding: utf-8 -*-
"""dashboard.service 聚合函数单测（P1：db_sellin_summary）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.dashboard import service
from app.models.dealer_sales import DealerSales


class DbSellinSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "pdca-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self._seed()

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self):
        rows = [
            ("2026-08-18", "Dealer A", 12.5, 3),
            ("2026-08-17", "Dealer A", 5.0, 1),
            ("2026-08-18", "Dealer B", 2.0, 0),
            ("2026-08-18", "Dealer Empty", 0.0, 0),
            ("2026-07-05", "Dealer A", 8.0, 2),
        ]
        with Session(self.engine) as session:
            for check_date, name, wan, units in rows:
                session.add(
                    DealerSales(
                        check_date=check_date,
                        dealer_name=name,
                        sell_in_wan=wan,
                        sell_out_wan=0.0,
                        units=units,
                    )
                )
            session.commit()

    def test_monthly_aggregate_skips_empty_rows(self):
        with Session(self.engine) as session:
            result = service.db_sellin_summary("2026-08", session, user=None)
        self.assertTrue(result["has_data"])
        # 空业绩行（wan=0 且 units=0）不进入榜单
        names = [item["name"] for item in result["dealers"]]
        self.assertNotIn("Dealer Empty", names)
        self.assertEqual(names, ["Dealer A", "Dealer B"])
        # Dealer A 当月 12.5+5.0=17.5 万，Dealer B 2.0 万
        self.assertEqual(result["total_wan"], 19.5)
        self.assertEqual(result["dealers"][0]["wan"], 17.5)
        self.assertEqual(result["dealers"][0]["rank"], 1)

    def test_trend_covers_six_months(self):
        with Session(self.engine) as session:
            result = service.db_sellin_summary("2026-08", session, user=None)
        self.assertEqual(len(result["trend"]), 6)
        self.assertEqual(result["trend"][-1]["month"], "2026-08")
        self.assertEqual(result["trend"][-1]["wan"], 19.5)
        self.assertEqual(result["trend"][-2]["wan"], 8.0)  # 2026-07


if __name__ == "__main__":
    unittest.main()
