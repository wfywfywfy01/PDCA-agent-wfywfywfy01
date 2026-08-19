# -*- coding: utf-8 -*-
"""P3：客户域（customer_profiles）导入与服务切 DB 单测。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.customer_profile import CustomerProfile


class CustomerDomainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'}"
        )
        SQLModel.metadata.create_all(self.engine)
        repo_root = Path(self.temp_dir.name) / "repo"
        (repo_root / "teams" / "yang-jingjing").mkdir(parents=True)
        (repo_root / "data_platform" / "data_role_pdca_mvp" / "config").mkdir(parents=True)
        self.settings = SimpleNamespace(
            repo_root=repo_root,
            config_dir=repo_root / "data_platform" / "data_role_pdca_mvp" / "config",
        )
        self.patches = [
            patch("app.database.get_engine", return_value=self.engine),
            patch("app.models.writes.get_engine", return_value=self.engine),
            patch("app.signalseller.service.get_settings", return_value=self.settings),
            patch("app.legacy.bridge.today_text", return_value="2026-08-19"),
        ]
        for item in self.patches:
            item.start()
        self.teams_root = repo_root / "teams"

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _write_csv(self, rows: list[dict]) -> Path:
        path = self.teams_root / "yang-jingjing" / "customers.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def _db_rows(self) -> list[CustomerProfile]:
        with Session(self.engine) as session:
            return list(session.exec(select(CustomerProfile)).all())

    def test_import_creates_rows_and_derives_abcd(self):
        from scripts.import_customers_csv import import_team_csv

        self._write_csv(
            [
                {
                    "region": "中东",
                    "country": "沙特",
                    "dealer_name": "Dealer X",
                    "owner": "何海文",
                    "priority": "A",
                    "status": "active",
                    "last_followup_date": "2026-08-10",
                    "next_action": "",
                    "abcd_grade": "",
                },
                {
                    "dealer_name": "Dealer Y",
                    "owner": "王宇彤",
                    "priority": "",
                    "abcd_grade": "C",
                },
            ]
        )
        with Session(self.engine) as session:
            count = import_team_csv("yang-jingjing", self.teams_root / "yang-jingjing" / "customers.csv", session)
        self.assertEqual(count, 2)
        rows = self._db_rows()
        self.assertEqual(len(rows), 2)
        by_name = {row.dealer_name: row for row in rows}
        self.assertEqual(by_name["Dealer X"].abcd_grade, "A")  # priority 推导
        self.assertEqual(by_name["Dealer Y"].abcd_grade, "C")  # 显式列优先

    def test_import_is_idempotent_upsert(self):
        from scripts.import_customers_csv import import_team_csv

        path = self._write_csv(
            [{"dealer_name": "Dealer Z", "owner": "何海文", "next_action": "初版"}]
        )
        with Session(self.engine) as session:
            import_team_csv("yang-jingjing", path, session)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            fh.write("dealer_name,owner,next_action\nDealer Z,何海文,更新版\n")
        with Session(self.engine) as session:
            import_team_csv("yang-jingjing", path, session)
        rows = self._db_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].next_action, "更新版")

    def test_load_customers_db_first(self):
        from app.signalseller import service

        with Session(self.engine) as session:
            session.add(
                CustomerProfile(
                    team="yang-jingjing",
                    dealer_name="DB Customer",
                    owner="何海文",
                    priority="A",
                    status="active",
                    last_followup_date="2026-08-01",
                    next_action="",
                )
            )
            session.commit()
        rows = service.load_customers("yang-jingjing")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["dealer_name"], "DB Customer")
        self.assertEqual(row["abcd_grade"], "A")
        self.assertEqual(row["silent_days"], 18)  # 08-01 → 08-19
        self.assertTrue(row["is_overdue"])  # A 类阈值 7 天

    def test_load_customers_csv_fallback_when_db_empty(self):
        from app.signalseller import service

        self._write_csv(
            [{"dealer_name": "CSV Only", "owner": "何海文", "priority": "B", "status": "active"}]
        )
        rows = service.load_customers("yang-jingjing")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dealer_name"], "CSV Only")
        self.assertEqual(rows[0]["abcd_grade"], "B")

    def test_list_owners_db_first(self):
        from app.signalseller import service

        with Session(self.engine) as session:
            session.add(
                CustomerProfile(team="yang-jingjing", dealer_name="X", owner="何海文")
            )
            session.commit()
        self.assertEqual(service.list_owners("yang-jingjing"), ["何海文"])


if __name__ == "__main__":
    unittest.main()
