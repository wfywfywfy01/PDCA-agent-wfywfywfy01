# -*- coding: utf-8 -*-
"""MTO 视觉服务测试：契约映射、无密钥待确认、4 款目标判定。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.agents.mto_vision_service import (
    MTO_DAILY_GOAL,
    MTO_QUOTE_MIN_WAN,
    quote_to_vision,
    review_owner_images,
)


class _SettingsStub:
    def __init__(self, qwen_key):
        self.qwen_api_key = qwen_key


class MtoVisionTests(unittest.TestCase):
    def test_quote_mapping_qualifies(self):
        result = quote_to_vision(
            "于冰",
            "mto:x",
            {
                "model": "AGENT Q",
                "sku": "AQ-1",
                "delivery": "鳄鱼皮",
                "target_customer": "迪拜",
                "usd": 47000.0,
                "wan": 32.8,
                "qualifies": True,
                "raw_ok": True,
            },
        )
        self.assertEqual(result.product, "AGENT Q")
        self.assertEqual(result.quote_wan, 32.8)
        self.assertTrue(result.qualifies)
        self.assertEqual(result.review_status, "verified")

    def test_missing_quote_not_qualified(self):
        result = quote_to_vision(
            "于冰",
            "mto:x",
            {"model": "", "usd": None, "wan": None, "qualifies": False, "raw_ok": False},
        )
        self.assertIsNone(result.qualifies)
        self.assertEqual(result.review_status, "pending_manual")
        self.assertEqual(result.product, "机型待确认")

    def test_review_uses_existing_dedup_and_emits_event(self):
        settings = _SettingsStub(qwen_key="has-key")
        fake_quotes = [
            {
                "model": "Signature S+",
                "sku": "S1",
                "delivery": "白金",
                "target_customer": "伦敦",
                "usd": 98500.0,
                "wan": 689.5,
                "qualifies": True,
                "raw_ok": True,
            },
        ]
        with patch(
            "app.agents.mto_vision_service.get_settings", return_value=settings
        ), patch(
            "app.mto_ocr.review_mto_images",
            return_value=(1, ["Signature S+"], fake_quotes),
        ), patch(
            "app.agents.mto_vision_service.write_event", MagicMock()
        ) as event_mock:
            payload = review_owner_images("于冰", [], 123, day="2026-09-17")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["qualify_count"], 1)
        self.assertEqual(payload["goal"], MTO_DAILY_GOAL)
        self.assertFalse(payload["goal_met"])  # 1 款 < 4 款目标
        self.assertTrue(event_mock.called)

    def test_no_key_amount_unknown(self):
        settings = _SettingsStub(qwen_key="")
        with patch(
            "app.agents.mto_vision_service.get_settings", return_value=settings
        ), patch(
            "app.mto_ocr.review_mto_images", return_value=(2, [], [])
        ), patch(
            "app.agents.mto_vision_service.write_event", MagicMock()
        ):
            payload = review_owner_images("Lina", [], 456, day="2026-09-17")
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["amount_unknown"])
        self.assertEqual(payload["qualify_count"], 0)

    def test_threshold_constant(self):
        self.assertEqual(MTO_QUOTE_MIN_WAN, 30.0)


if __name__ == "__main__":
    unittest.main()

