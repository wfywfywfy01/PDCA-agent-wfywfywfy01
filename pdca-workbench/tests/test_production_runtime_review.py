"""Production review regressions: honest health, bounded metrics, scoped cleanup."""
import asyncio
import json
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from starlette.requests import Request
from starlette.responses import Response

from app.main import health, metrics_middleware
from app import metrics
from scripts import server_cleanup
from scripts.acceptance_smoke import snapshot_matches


class RuntimeReviewTests(unittest.TestCase):
    def test_acceptance_never_waives_wrong_snapshot_total_for_a_source_label(self):
        self.assertFalse(snapshot_matches({"source": "dealer_sales_db_latest_snapshot", "has_data": True, "total_wan": 99}, 12))
        self.assertFalse(snapshot_matches({"source": "live", "has_data": True, "total_wan": 12}, 12))
        self.assertFalse(snapshot_matches({"source": "dealer_sales_db_latest_snapshot", "has_data": False, "total_wan": None}, 0))
        self.assertTrue(snapshot_matches({"source": "dealer_sales_db_latest_snapshot", "has_data": True, "total_wan": 12}, 12))

    def test_unknown_http_methods_share_one_metric_series(self):
        with patch.object(metrics, "_requests_by_path", defaultdict(int)):
            for method in ("CUSTOM0", "CUSTOM1", "CUSTOM2"):
                metrics.record_request(method, "<unmatched>", 405)
            self.assertEqual(dict(metrics._requests_by_path), {"OTHER <unmatched>": 3})

    def test_health_probes_database_instead_of_trusting_startup_mode(self):
        with (
            patch("app.main.get_db_mode", return_value="postgresql"),
            patch("app.main.check_db_connection", return_value=False) as probe,
            patch("app.main.get_settings", return_value=SimpleNamespace(
                environment="production", scheduler_enabled=False, require_vertu=False)),
            patch("app.main.backup_status", return_value={"ok": True}),
            patch.dict("os.environ", {"PDCA_RELEASE_SHA": "a" * 40}),
        ):
            result = asyncio.run(health())
        probe.assert_called_once_with()
        self.assertEqual(result.status_code, 503)
        self.assertFalse(json.loads(result.body)["database_connected"])
        self.assertEqual(json.loads(result.body)["revision"], "a" * 40)

    def test_metrics_use_route_template_without_private_identifier(self):
        request = Request({"type": "http", "method": "GET", "headers": [], "path": "/api/stores/private-store",
                           "route": SimpleNamespace(path="/api/stores/{store_id}")})
        with patch("app.main.record_request") as record:
            asyncio.run(metrics_middleware(request, AsyncMock(return_value=Response(status_code=200))))
        record.assert_called_once_with("GET", "/api/stores/{store_id}", 200)

    def test_metrics_record_unhandled_failures_under_bounded_label(self):
        request = Request({"type": "http", "method": "GET", "headers": [], "path": "/random-private-value"})
        with patch("app.main.record_request") as record:
            with self.assertRaises(RuntimeError):
                asyncio.run(metrics_middleware(request, AsyncMock(side_effect=RuntimeError("failed"))))
        record.assert_called_once_with("GET", "<unmatched>", 500)

    def test_cleanup_never_prunes_other_projects_or_live_or_recent_images(self):
        now = 2_000_000
        own = "ghcr.io/wfywfywfy01/pdca-workbench:"
        images = [
            {"Id": "new-a", "RepoTags": [own + "a"], "Created": now - 1},
            {"Id": "new-b", "RepoTags": [own + "b"], "Created": now - 2},
            {"Id": "live", "RepoTags": [own + "live"], "Created": 1},
            {"Id": "other", "RepoTags": ["other-project:old"], "Created": 1},
            {"Id": "mixed", "RepoTags": [own + "mixed", "other:old"], "Created": 1},
            {"Id": "unknown", "RepoTags": [], "Created": 1},
            {"Id": "old", "RepoTags": [own + "old"], "Created": 1},
        ]
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path))
            if request.url.path == "/images/json":
                return httpx.Response(200, json=images)
            if request.url.path == "/containers/json":
                return httpx.Response(200, json=[{"ImageID": "live"}])
            self.assertEqual(request.method, "DELETE")
            self.assertEqual(request.url.params["force"], "false")
            return httpx.Response(200, json=[{"Deleted": "old"}])

        with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://docker") as client:
            with patch("scripts.server_cleanup.time.time", return_value=now):
                self.assertEqual(server_cleanup.cleanup_images(client), 1)
        self.assertEqual([path for method, path in requests if method == "DELETE"], ["/images/old"])
        self.assertFalse(any("prune" in path for _, path in requests))

    def test_cleanup_api_failure_is_not_reported_as_success(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)),
                          base_url="http://docker") as client:
            with self.assertRaises(httpx.HTTPStatusError):
                server_cleanup.cleanup_images(client)
