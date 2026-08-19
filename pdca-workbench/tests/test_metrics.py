# -*- coding: utf-8 -*-
"""P5：/metrics 指标模块单测。"""
from __future__ import annotations

import unittest

from app import metrics


def _metric_value(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(name + " ") and not line.startswith("#"):
            return line[len(name) + 1 :]
    raise AssertionError(f"metric {name} not found")


class MetricsTests(unittest.TestCase):
    def test_record_request_accumulates(self):
        before = int(_metric_value(metrics.export_prometheus(), "pdca_requests_total"))
        metrics.record_request("GET", "/api/dashboard/overview", 200)
        metrics.record_request("POST", "/api/walkin-metrics", 500)
        text = metrics.export_prometheus()
        self.assertEqual(_metric_value(text, "pdca_requests_total"), str(before + 2))
        self.assertIn('pdca_http_status_total{status="200"}', text)
        self.assertIn('pdca_http_status_total{status="500"}', text)
        self.assertEqual(_metric_value(text, "pdca_errors_total"), "1")
        self.assertIn('pdca_requests_by_path_total{path="GET /api/dashboard/overview"}', text)

    def test_metrics_self_path_excluded(self):
        metrics.record_request("GET", "/metrics", 200)
        text = metrics.export_prometheus()
        self.assertNotIn('path="GET /metrics"', text)

    def test_mark_sync_reflects_in_export(self):
        metrics.mark_sync(True)
        text = metrics.export_prometheus()
        self.assertIn("pdca_sync_last_success_ok 1.0", text)
        self.assertIn("pdca_sync_last_success_timestamp_seconds", text)
        metrics.mark_sync(False)
        text = metrics.export_prometheus()
        self.assertIn("pdca_sync_last_success_ok 0.0", text)

    def test_backup_freshness_injected(self):
        text = metrics.export_prometheus(backup_status_fn=lambda: {"ok": True})
        self.assertIn("pdca_backup_fresh 1", text)
        text = metrics.export_prometheus(backup_status_fn=lambda: {"ok": False})
        self.assertIn("pdca_backup_fresh 0", text)

    def test_export_never_raises_on_bad_backup_fn(self):
        text = metrics.export_prometheus(backup_status_fn=lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertIn("pdca_backup_fresh 0", text)


if __name__ == "__main__":
    unittest.main()
