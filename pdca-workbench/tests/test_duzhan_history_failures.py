# -*- coding: utf-8 -*-
"""群历史取数失败时，台账不能把未知结果当作零或未报。"""
import unittest
from unittest.mock import patch


class HistoryFailureTests(unittest.TestCase):
    def test_fetch_distinguishes_failed_request_from_empty_history(self):
        from app.duzhan_ledger import fetch_channel_history

        with patch("app.vertu.client.run_vertu_sync_json", return_value={"messages": []}):
            self.assertEqual(fetch_channel_history("channel", "2026-10-12"), [])
        with self.assertRaises(ValueError):
            fetch_channel_history("", "2026-10-12")
        for payload in (None, {}, {"messages": None}, {"ok": False, "messages": []},
                        {"error": "unauthorized", "messages": []}):
            with self.subTest(payload=payload), patch(
                "app.vertu.client.run_vertu_sync_json", return_value=payload
            ):
                with self.assertRaises(RuntimeError):
                    fetch_channel_history("channel", "2026-10-12")

    def test_failed_report_and_owner_history_remain_unknown(self):
        from app import duzhan_ledger as ledger

        owner = next(item for item in ledger.OWNERS if item.display == "于冰")
        with patch.object(ledger, "OWNERS", (owner,)), patch.object(
            ledger, "fetch_personal_okr", return_value=[]
        ), patch.object(ledger, "load_vps_activity", return_value={}), patch.object(
            ledger, "fetch_vemory_day", return_value=None
        ), patch.object(
            ledger, "fetch_channel_history", side_effect=RuntimeError("IM unavailable")
        ), patch.object(
            ledger, "_mcp_bundle", return_value=(None, None, None)
        ), patch("app.mto_ocr.review_mto_images", return_value=(0, [], [])) as ocr:
            result = ledger.collect_ledger("2026-10-12")

        row = result["people"][0]
        self.assertFalse(row["daily_report_ok"])
        self.assertNotIn("未报今日任务", row["gaps"])
        self.assertIsNone(row["mto_count"])
        ocr.assert_not_called()
