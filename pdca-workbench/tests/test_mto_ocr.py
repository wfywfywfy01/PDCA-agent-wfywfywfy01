# -*- coding: utf-8 -*-
"""MTO 报价 OCR：结构化字段；磁盘文件核对后删除。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.mto_ocr import parse_quote_text, summarize_quotes


class MtoOcrTests(unittest.TestCase):
    def test_parse_quote_and_30wan(self):
        text = '{"model":"Agent Q","total_usd":107000,"delivery":"2026-11-05","sku":"VertuAgentQ-X","target_customer":""}'
        row = parse_quote_text(text)
        self.assertEqual(row["model"], "Agent Q")
        self.assertEqual(row["usd"], 107000.0)
        self.assertTrue(row["qualifies"])
        self.assertEqual(row["target_customer"], "")

    def test_signature_under_threshold(self):
        text = '{"model":"Signature S+","total_usd":2010,"target_customer":""}'
        row = parse_quote_text(text)
        self.assertFalse(row["qualifies"])
        self.assertAlmostEqual(row["wan"] or 0, 1.4, places=1)

    def test_summarize_marks_missing_customer(self):
        qualify_n, names = summarize_quotes(
            [
                parse_quote_text(
                    '{"model":"Agent Q","total_usd":61740,"target_customer":""}'
                )
            ]
        )
        self.assertEqual(qualify_n, 1)
        self.assertIn("目标客户待确认", names[0])
        self.assertIn("达标", names[0])

    def test_garbage_is_unread(self):
        row = parse_quote_text("not json")
        self.assertFalse(row["raw_ok"])
        self.assertIsNone(row["usd"])

    def test_tmp_dir_removed_after_ocr(self):
        from pathlib import Path

        from app.mto_ocr import download_ocr_delete

        kept: list[Path] = []

        def fake_ocr(content: bytes, mime: str = "image/jpeg") -> dict:
            del content, mime
            return parse_quote_text('{"model":"Q","total_usd":50000,"target_customer":"AF"}')

        class FakeResp:
            content = b"fake-bytes"
            headers = {"content-type": "image/webp"}

        with patch("app.mto_ocr._vps_auth", return_value=("https://example.invalid", {})), \
            patch("app.mto_ocr.httpx.get", return_value=FakeResp()), \
            patch("app.mto_ocr.ocr_image_bytes", side_effect=fake_ocr), \
            patch("app.mto_ocr.tempfile.mkdtemp", return_value=str(Path.cwd() / "_mto_test_tmp")):
            tmp = Path.cwd() / "_mto_test_tmp"
            tmp.mkdir(exist_ok=True)
            kept.append(tmp)
            result = download_ocr_delete("/v1/im/files/x")
        self.assertEqual(result["target_customer"], "AF")
        self.assertFalse(tmp.exists())


if __name__ == "__main__":
    unittest.main()
