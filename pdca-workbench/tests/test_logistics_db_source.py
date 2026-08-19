# -*- coding: utf-8 -*-
"""P2：物流读取侧切 DB（logistics_shipments 转正）单测。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import SQLModel, create_engine

from app.models.logistics import LogisticsShipment


def _settings(temp_dir: Path) -> SimpleNamespace:
    mvp_root = temp_dir / "mvp"
    (mvp_root / "inputs" / "logistics").mkdir(parents=True, exist_ok=True)
    (mvp_root / "config").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        mvp_root=mvp_root,
        config_dir=mvp_root / "config",
        include_demo_data=False,
    )


class LogisticsDbSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'}"
        )
        SQLModel.metadata.create_all(self.engine)
        self.settings = _settings(Path(self.temp_dir.name))
        import json as _json

        (self.settings.config_dir / "carriers.json").write_text(
            _json.dumps({"UPS": {"tracking_url": "https://example.invalid/{tracking_number}"}}),
            encoding="utf-8",
        )
        self.patches = [
            patch("app.logistics.service.get_settings", return_value=self.settings),
            patch("app.database.get_engine", return_value=self.engine),
            patch("app.models.writes.get_engine", return_value=self.engine),
            patch("app.legacy.bridge.today_text", return_value="2026-08-19"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed_db(self, rows: list[dict]) -> None:
        from sqlmodel import Session

        with Session(self.engine) as session:
            for row in rows:
                session.add(LogisticsShipment(**row))
            session.commit()

    def _seed_csv(self, date_text: str, rows: list[dict]) -> None:
        import csv

        path = self.settings.mvp_root / "inputs" / "logistics" / f"{date_text}_tracking.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "tracking_number", "carrier", "customer", "salesperson",
                    "ship_date", "expected_status", "current_status", "note",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_db_rows_are_loaded_and_enriched(self):
        from app.logistics import service

        self._seed_db(
            [
                {
                    "record_date": "2026-08-18",
                    "tracking_number": "DB123",
                    "carrier": "UPS",
                    "customer": "客户甲",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-10",
                    "current_status": "Delivered",
                }
            ]
        )
        rows = service.load_shipments(date_text="all")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tracking_number"], "DB123")
        self.assertEqual(row["judgement"], "正常")  # Delivered → 已签收
        self.assertTrue(row["is_delivered"])
        self.assertTrue(row["tracking_url"])  # carriers.json 兜底模板

    def test_db_wins_over_same_tracking_in_csv(self):
        from app.logistics import service

        self._seed_db(
            [
                {
                    "record_date": "2026-08-19",
                    "tracking_number": "SAME123",
                    "carrier": "DHL",
                    "customer": "库内客户",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-12",
                    "current_status": "运输中",
                }
            ]
        )
        self._seed_csv(
            "2026-08-19",
            [
                {
                    "tracking_number": "SAME123",
                    "carrier": "DHL",
                    "customer": "旧CSV客户",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-12",
                    "current_status": "异常: 清关失败",
                    "note": "",
                }
            ],
        )
        rows = service.load_shipments(date_text="all")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer"], "库内客户")  # DB 优先

    def test_csv_fills_missing_tracking(self):
        from app.logistics import service

        self._seed_db(
            [
                {
                    "record_date": "2026-08-19",
                    "tracking_number": "DB-ONLY",
                    "carrier": "UPS",
                    "customer": "甲",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-12",
                    "current_status": "",
                }
            ]
        )
        self._seed_csv(
            "2026-08-17",
            [
                {
                    "tracking_number": "CSV-ONLY",
                    "carrier": "FedEx",
                    "customer": "乙",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-10",
                    "current_status": "In transit",
                    "note": "",
                }
            ],
        )
        rows = service.load_shipments(date_text="all")
        trackings = {row["tracking_number"] for row in rows}
        self.assertEqual(trackings, {"DB-ONLY", "CSV-ONLY"})

    def test_available_dates_union_db_and_csv(self):
        from app.logistics import service

        self._seed_db(
            [
                {
                    "record_date": "2026-08-19",
                    "tracking_number": "X1",
                    "carrier": "UPS",
                    "customer": "甲",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-19",
                    "current_status": "",
                }
            ]
        )
        self._seed_csv(
            "2026-08-10",
            [
                {
                    "tracking_number": "X2",
                    "carrier": "UPS",
                    "customer": "乙",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-10",
                    "current_status": "",
                    "note": "",
                }
            ],
        )
        dates = service.list_available_dates()
        self.assertEqual(dates, ["2026-08-19", "2026-08-10"])

    def test_demo_records_filtered_in_db_source(self):
        from app.logistics import service

        self._seed_db(
            [
                {
                    "record_date": "2026-08-19",
                    "tracking_number": "1Z0000000000000000",
                    "carrier": "UPS",
                    "customer": "演示",
                    "salesperson": "何海文",
                    "ship_date": "2026-08-19",
                    "current_status": "",
                }
            ]
        )
        self.assertEqual(service.load_shipments(date_text="all"), [])

    def test_create_shipment_writes_db_and_csv(self):
        from sqlmodel import Session, select

        from app.logistics import service
        from app.models.logistics import LogisticsShipment

        with patch("app.legacy.bridge.append_logistics") as append_mock:
            tracking = service.create_shipment(
                "2026-08-19",
                {
                    "tracking_number": "NEW123",
                    "carrier": "UPS",
                    "customer": "新客户",
                    "ship_date": "2026-08-19",
                    "current_status": "",
                    "note": "测试",
                },
                salesperson="何海文",
            )
        self.assertEqual(tracking, "NEW123")
        append_mock.assert_called_once()
        with Session(self.engine) as session:
            row = session.exec(
                select(LogisticsShipment).where(
                    LogisticsShipment.tracking_number == "NEW123"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.customer, "新客户")
        self.assertEqual(row.salesperson, "何海文")
        # 录入后立即可在 DB-first 读取侧看到
        rows = service.load_shipments(date_text="all")
        self.assertIn("NEW123", {r["tracking_number"] for r in rows})

    def test_create_shipment_rejects_blank_tracking(self):
        from app.logistics import service

        with self.assertRaises(ValueError):
            service.create_shipment("2026-08-19", {"tracking_number": "  "})


if __name__ == "__main__":
    unittest.main()
