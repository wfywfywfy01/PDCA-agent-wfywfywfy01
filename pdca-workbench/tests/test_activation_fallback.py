import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.vertu import activation
from app.walkin.router import _scope_activation_payload


class ActivationFallbackTests(unittest.TestCase):
    def setUp(self):
        activation._ACTIVATION_CACHE.update(
            {"ts": 0.0, "value": None, "retry_after": 0.0, "error": None}
        )

    def test_legacy_sandbox_result_is_unwrapped_and_cached(self):
        envelope = {
            "validation": {"ok": True, "issues": []},
            "execution": {
                "result": {
                    "dealers": [{"dealer_name": "Dealer A", "shipped": 4, "activated": 3}],
                    "products": [],
                    "total_shipped": 4,
                    "total_activated": 3,
                }
            },
        }
        settings = SimpleNamespace(mvp_root=Path("/mvp"))
        with (
            patch("app.vertu.activation.get_settings", return_value=settings),
            patch("app.vertu.activation.Path.is_file", return_value=True),
            patch(
                "app.vertu.activation.run_legacy_vertu_json",
                new=AsyncMock(return_value=envelope),
            ) as run,
        ):
            result = asyncio.run(activation.fetch_dealer_activation(force=True))

        run.assert_awaited_once_with(
            [
                "odoo",
                "data",
                "sandbox",
                "--code-file",
                str(settings.mvp_root / "system_queries" / "dealer_activation_stats.py"),
            ],
            timeout=45.0,
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "legacy-vertu:mobile.activation.report")
        self.assertEqual(result["total_activated"], 3)

    def test_stale_cache_is_served_when_refresh_fails(self):
        activation._ACTIVATION_CACHE.update(
            {
                "ts": 0.0,
                "value": {"ok": True, "available": True, "dealers": [], "stale": False},
            }
        )
        query = AsyncMock(side_effect=activation.ActivationQueryError("offline"))
        with patch(
            "app.vertu.activation._query_activation_source",
            new=query,
        ):
            result = asyncio.run(activation.fetch_dealer_activation(force=True))
            cooled_down = asyncio.run(activation.fetch_dealer_activation())

        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])
        self.assertIn("上次成功结果", result["detail"])
        self.assertTrue(cooled_down["stale"])
        self.assertEqual(query.await_count, 1)

    def test_role_scope_recalculates_classified_local_rate(self):
        payload = {
            "dealers": [
                {
                    "dealer_name": "Dealer A",
                    "shipped": 10,
                    "activated": 8,
                    "not_activated": 2,
                    "local_activated": 3,
                    "remote_activated": 2,
                },
                {
                    "dealer_name": "Dealer B",
                    "shipped": 5,
                    "activated": 5,
                    "not_activated": 0,
                    "local_activated": 5,
                    "remote_activated": 0,
                },
            ],
            "products": [{"product_name": "Hidden aggregate"}],
        }

        result = _scope_activation_payload(payload, ["Dealer A"])

        self.assertEqual([row["dealer_name"] for row in result["dealers"]], ["Dealer A"])
        self.assertEqual(result["total_shipped"], 10)
        self.assertEqual(result["total_activated"], 8)
        self.assertEqual(result["overall_local_rate"], 60.0)
        self.assertIsNone(result["total_overseas_stock"])
        self.assertEqual(result["products"], [])


if __name__ == "__main__":
    unittest.main()
