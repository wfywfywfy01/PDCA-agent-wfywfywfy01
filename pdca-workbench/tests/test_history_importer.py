# -*- coding: utf-8 -*-
"""历史导入器单测（P1③）：结构解析、每月选取、空文件不遮蔽。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKBENCH_ROOT = Path(__file__).resolve().parents[1]
if str(WORKBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_ROOT))

from scripts.import_history_dealer_sales import (  # noqa: E402
    _extract_rows,
    _file_month,
    discover_monthly_snapshots,
)


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class HistoryImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_raw = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _mkfile(self, name: str, payload, mtime: float) -> Path:
        path = self.data_raw / name
        _write(path, payload)
        import os

        os.utime(path, (mtime, mtime))
        return path

    def test_extract_rows_ps1_shape(self):
        payload = {"execution": {"result": {"customer_summary": [
            {"partner_name": "A", "performance": 100, "quantity": 1},
        ]}}}
        rows = _extract_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["partner_name"], "A")

    def test_extract_rows_sandbox_shape(self):
        payload = {"result": {"execution": {"result": {"customer_summary": [
            {"partner_name": "B", "performance": 200, "quantity": 2},
        ]}}}}
        rows = _extract_rows(payload)
        self.assertEqual(rows[0]["partner_name"], "B")

    def test_extract_rows_flat_shape(self):
        rows = _extract_rows({"dealers": [{"dealer_name": "C"}]})
        self.assertEqual(rows[0]["dealer_name"], "C")

    def test_empty_payload_returns_empty(self):
        self.assertEqual(_extract_rows({"execution": {"result": {"customer_summary": []}}}), [])

    def test_file_month_parses_range_and_single(self):
        self.assertEqual(
            _file_month(Path("dealer_sales_month_to_date_2026-07-01_to_2026-07-14.json")),
            ("2026-07-14", "2026-07"),
        )
        self.assertEqual(
            _file_month(Path("dealer_sales_month_to_date_2026-06-29.json")),
            ("2026-06-29", "2026-06"),
        )

    def test_discovery_prefers_latest_with_rows_over_empty_newer(self):
        real = {"result": {"execution": {"result": {"customer_summary": [
            {"partner_name": "X", "performance": 999, "quantity": 1},
        ]}}}}
        empty = {"execution": {"result": {"customer_summary": []}}}
        # 有数据的旧文件（mtime 早）vs 空的新文件（mtime 晚）
        self._mkfile("dealer_sales_month_to_date_2026-07-14.json", real, 1000.0)
        self._mkfile("dealer_sales_month_to_date_2026-07-01_to_2026-07-29.json", empty, 2000.0)
        self._mkfile("dealer_sales_month_to_date_2026-07-29.params.json", {}, 3000.0)
        snapshots = discover_monthly_snapshots(self.data_raw)
        self.assertEqual(set(snapshots), {"2026-07"})
        self.assertIn("2026-07-14.json", snapshots["2026-07"].name)

    def test_discovery_picks_newest_when_all_have_rows(self):
        real_old = {"execution": {"result": {"customer_summary": [
            {"partner_name": "X", "performance": 1, "quantity": 1},
        ]}}}
        real_new = {"execution": {"result": {"customer_summary": [
            {"partner_name": "Y", "performance": 2, "quantity": 2},
        ]}}}
        self._mkfile("dealer_sales_month_to_date_2026-05-01_to_2026-05-10.json", real_old, 1000.0)
        self._mkfile("dealer_sales_month_to_date_2026-05-01_to_2026-05-20.json", real_new, 2000.0)
        snapshots = discover_monthly_snapshots(self.data_raw)
        self.assertIn("2026-05-20.json", snapshots["2026-05"].name)


if __name__ == "__main__":
    unittest.main()
