# -*- coding: utf-8 -*-
"""豆包 ASR 适配器测试：规范化、重试、超限与 sha 去重。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.agents.asr_doubao import (
    MAX_AUDIO_BYTES,
    AsrError,
    DoubaoFlashAsr,
    sha256_of,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class DoubaoAsrTests(unittest.TestCase):
    def setUp(self):
        self.adapter = DoubaoFlashAsr(
            base_url="https://openspeech.bytedance.com",
            app_key="app-1",
            access_key="access-1",
            api_key="api-1",
            resource_id="volc.bigasr.auc_turbo",
            timeout_seconds=5.0,
        )

    def test_configured_flag(self):
        self.assertTrue(self.adapter.configured)
        blank = DoubaoFlashAsr(app_key="", access_key="")
        self.assertFalse(blank.configured)

    def test_normalize_response(self):
        payload = {
            "result": {
                "text": "客户确认周五安排付款",
                "confidence": 0.91,
                "utterances": [
                    {
                        "speaker": "1",
                        "definite": True,
                        "words": [
                            {"text": "客户", "start_time": 480, "end_time": 980},
                            {"text": "确认", "start_time": 980, "end_time": 1480},
                        ],
                    }
                ],
            }
        }
        result = self.adapter._normalize(payload, "audio/mpeg")
        self.assertEqual(result.status, "completed")
        self.assertIn("客户确认", result.text)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].start_ms, 480)
        self.assertEqual(result.segments[0].end_ms, 1480)
        self.assertFalse(result.needs_manual_review)

    def test_low_confidence_needs_review(self):
        payload = {"result": {"text": "", "confidence": 0.4, "utterances": []}}
        result = self.adapter._normalize(payload, "audio/mpeg")
        self.assertTrue(result.needs_manual_review)

    def test_recognize_ok(self):
        payload = {"result": {"text": "ok", "confidence": 0.9, "utterances": []}}
        with patch("httpx.post", return_value=_FakeResponse(200, payload)):
            result = self.adapter.recognize(b"audio-bytes")
        self.assertEqual(result.text, "ok")

    def test_retry_on_5xx_then_success(self):
        payload = {"result": {"text": "ok", "confidence": 0.9, "utterances": []}}
        responses = [_FakeResponse(503, {}, "busy"), _FakeResponse(200, payload)]
        with patch("httpx.post", side_effect=responses) as post_mock:
            result = self.adapter.recognize(b"audio-bytes")
        self.assertEqual(result.text, "ok")
        self.assertEqual(post_mock.call_count, 2)

    def test_client_error_no_retry(self):
        with patch(
            "httpx.post", return_value=_FakeResponse(400, {}, "bad request")
        ) as post_mock:
            with self.assertRaises(AsrError) as ctx:
                self.adapter.recognize(b"audio-bytes")
        self.assertEqual(ctx.exception.code, "http_400")
        self.assertEqual(post_mock.call_count, 1)

    def test_too_large_audio_rejected(self):
        with self.assertRaises(AsrError) as ctx:
            self.adapter.recognize(b"x" * (MAX_AUDIO_BYTES + 1))
        self.assertEqual(ctx.exception.code, "audio_too_large")

    def test_not_configured_rejected(self):
        blank = DoubaoFlashAsr(app_key="", access_key="")
        with self.assertRaises(AsrError) as ctx:
            blank.recognize(b"audio-bytes")
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_sha256_stable(self):
        self.assertEqual(
            sha256_of(b"same-audio"), sha256_of(b"same-audio")
        )
        self.assertNotEqual(sha256_of(b"same-audio"), sha256_of(b"other-audio"))


if __name__ == "__main__":
    unittest.main()
