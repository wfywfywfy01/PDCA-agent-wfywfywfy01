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

    def test_vps_auth_prefers_env_over_stale_session_file(self):
        """回归：旧会话文件过期导致附件下载 401、MTO 读不出报价；环境变量优先。"""
        import os

        from app.mto_ocr import _vps_auth

        with patch.dict(
            os.environ,
            {
                "VERTU_APP_KEY": "env-key",
                "VERTU_APP_ID": "env-app",
                "VERTU_USER_LOGIN": "env@vertu.cn",
                "VERTU_VPS_SERVICE_URL": "https://vps.vertu.cn",
            },
        ):
            base, headers = _vps_auth()
        self.assertEqual(base, "https://vps.vertu.cn")
        self.assertEqual(headers["Authorization"], "Bearer env-key")
        self.assertEqual(headers["x-vertu-agent-app-id"], "env-app")
        self.assertEqual(headers["x-vertu-user-login"], "env@vertu.cn")

    def test_webp_converted_to_png_before_ocr(self):
        """回归：本地 Qwen 网关 webp 直传读不出，须先转 PNG。

        CI 单元测试环境不装 Pillow（生产镜像内有）；无 Pillow 时跳过，
        转码行为已在生产容器实测验证。
        """
        import base64
        import io

        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装（CI 单元测试环境）")

        from app.mto_ocr import ocr_image_bytes

        # 生成一张 2x2 的 webp
        raw = io.BytesIO()
        Image.new("RGB", (2, 2), (200, 30, 30)).save(raw, format="WEBP")
        webp_bytes = raw.getvalue()
        captured: dict = {}

        def fake_post(url, json=None, headers=None, timeout=None, verify=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            data_url = json["messages"][0]["content"][1]["image_url"]["url"]
            captured["data_head"] = base64.b64decode(data_url.split(",", 1)[1])[:8]

        with patch("app.mto_ocr.get_settings") as settings_mock, patch(
            "app.mto_ocr.httpx.post", side_effect=fake_post
        ):
            settings_mock.return_value.qwen_base_url = "https://qwen3.vertu.cn:8443"
            settings_mock.return_value.qwen_api_key = "k"
            settings_mock.return_value.qwen_model = "qwen3.8-27b"
            ocr_image_bytes(webp_bytes, "image/webp")
        image_url = captured["json"]["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertEqual(
            captured["data_head"],
            bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
            "提交的应是 PNG 魔数",
        )

    def test_length_truncation_retries_with_direct_json(self):
        """回归：reasoning 吃满预算（finish_reason=length、无 JSON）时重试一次直接输出 JSON。"""
        import base64
        import io

        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装（CI 单元测试环境）")

        from app.mto_ocr import ocr_image_bytes

        raw = io.BytesIO()
        Image.new("RGB", (2, 2), (10, 10, 10)).save(raw, format="PNG")
        png_bytes = raw.getvalue()

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        calls = []

        def fake_post(url, json=None, headers=None, timeout=None, verify=None):
            calls.append(json)
            if len(calls) == 1:
                return FakeResp({
                    "choices": [{
                        "finish_reason": "length",
                        "message": {"content": "大量推理文本，但没有 JSON"},
                    }],
                })
            return FakeResp({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"model":"Quantum","total_usd":45022,"target_customer":""}'
                    },
                }],
            })

        with patch("app.mto_ocr.get_settings") as settings_mock, patch(
            "app.mto_ocr.httpx.post", side_effect=fake_post
        ):
            settings_mock.return_value.qwen_base_url = "https://qwen3.vertu.cn:8443"
            settings_mock.return_value.qwen_api_key = "k"
            settings_mock.return_value.qwen_model = "qwen3.8-27b"
            result = ocr_image_bytes(png_bytes, "image/png")
        self.assertTrue(result["raw_ok"])
        self.assertEqual(result["model"], "Quantum")
        self.assertEqual(len(calls), 2)
        # 第二次请求带“直接输出 JSON”引导
        steered = calls[1]["messages"][-1]["content"]
        self.assertIn("JSON", steered)


if __name__ == "__main__":
    unittest.main()
