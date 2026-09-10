# -*- coding: utf-8 -*-
"""dashboard.service 聚合函数单测（P1：db_sellin_summary）。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.dashboard import service
from app.models.dealer_sales import DealerSales
from app.models.sync import sync_dealer_sales_from_vps
from app.auth.models import User


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
                        source_file="vertu-cli:sales-orders:validated",
                        synced_at=datetime(2026, 8, 29, 14, 0, 15),
                    )
                )
            session.commit()

    def test_monthly_summary_uses_latest_snapshot_and_skips_empty_rows(self):
        with Session(self.engine) as session:
            result = service.db_sellin_summary("2026-08", session, user=None)
        self.assertTrue(result["has_data"])
        # 空业绩行（wan=0 且 units=0）不进入榜单
        names = [item["name"] for item in result["dealers"]]
        self.assertNotIn("Dealer Empty", names)
        self.assertEqual(names, ["Dealer A", "Dealer B"])
        # 每个 check_date 都是月累计快照，只能取 08-18 最新批次，不能逐日相加。
        self.assertEqual(result["total_wan"], 14.5)
        self.assertEqual(result["dealers"][0]["wan"], 12.5)
        self.assertEqual(result["dealers"][0]["rank"], 1)
        self.assertEqual(result["source"], "dealer_sales_db_latest_snapshot")
        self.assertEqual(result["as_of"], "2026-08-29T14:00:15+00:00")

    def test_trend_covers_six_months(self):
        with Session(self.engine) as session:
            result = service.db_sellin_summary("2026-08", session, user=None)
        self.assertEqual(len(result["trend"]), 6)
        self.assertEqual(result["trend"][-1]["month"], "2026-08")
        self.assertEqual(result["trend"][-1]["wan"], 14.5)
        self.assertEqual(result["trend"][-2]["wan"], 8.0)  # 2026-07

    def test_confirmed_empty_refresh_replaces_old_snapshot_with_live_zero(self):
        with (
            patch("app.models.sync.get_engine", return_value=self.engine),
            patch("app.vertu.sales.fetch_dealer_sales_orders_sync", return_value={
                "ok": True, "dealers": [], "total": 0,
            }),
        ):
            self.assertEqual(sync_dealer_sales_from_vps("2026-08-18"), 0)
        with Session(self.engine) as session:
            data = service.merge_db_sales(
                {}, "2026-08-18", session,
                User(username="admin", hashed_password="unused", role="admin", data_scope="all"),
                period="month",
            )
        self.assertEqual(data["sellInWan"], 0)
        self.assertEqual(data["dataState"]["sellIn"], "live")

        with Session(self.engine) as session:
            scoped = service.db_sellin_summary(
                "2026-08", session,
                User(username="sales", hashed_password="unused", role="sales", data_scope="self"),
            )
        self.assertTrue(scoped["has_data"])
        self.assertEqual(scoped["total_wan"], 0)
        self.assertEqual(scoped["dealers"], [])

    def test_failed_refresh_keeps_last_snapshot_but_marks_it_stale(self):
        with (
            patch("app.models.sync.get_engine", return_value=self.engine),
            patch("app.vertu.sales.fetch_dealer_sales_orders_sync", side_effect=RuntimeError("offline")),
            self.assertRaises(RuntimeError),
        ):
            sync_dealer_sales_from_vps("2026-08-19")
        with Session(self.engine) as session:
            summary = service.db_sellin_summary("2026-08", session, user=None)
            overview = service.merge_db_sales(
                {}, "2026-08-19", session,
                User(username="admin", hashed_password="unused", role="admin", data_scope="all"),
                period="month",
            )
        self.assertEqual(summary["amount_state"], "stale")
        self.assertEqual(summary["total_wan"], 14.5)
        self.assertIn("上一次成功", summary["amount_message"])
        self.assertEqual(overview["sellInWan"], 14.5)
        self.assertEqual(overview["dataState"]["sellIn"], "stale")

    def test_first_failed_refresh_clears_legacy_amount_and_marks_stale(self):
        with (
            patch("app.models.sync.get_engine", return_value=self.engine),
            patch("app.vertu.sales.fetch_dealer_sales_orders_sync", side_effect=RuntimeError("offline")),
            self.assertRaises(RuntimeError),
        ):
            sync_dealer_sales_from_vps("2026-09-01")
        with Session(self.engine) as session:
            summary = service.db_sellin_summary("2026-09", session, user=None)
            overview = service.merge_db_sales(
                {"sellInWan": 999, "sellInAmount": "legacy", "dataState": {"sellIn": "live"}},
                "2026-09-01", session,
                User(username="admin", hashed_password="unused", role="admin", data_scope="all"),
                period="month",
            )
        self.assertEqual(summary["amount_state"], "stale")
        self.assertFalse(summary["has_data"])
        self.assertIsNone(summary["total_wan"])
        self.assertIsNone(summary["trend"][-1]["wan"])
        self.assertIsNone(overview["sellInWan"])
        self.assertEqual(overview["dataState"]["sellIn"], "stale")


if __name__ == "__main__":
    unittest.main()
