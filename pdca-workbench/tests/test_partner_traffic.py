"""Traffic is page evidence, never a customer or financial conversion."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.growth import ga4, partner_traffic as traffic


def response(dimensions=(), rows=(), count=None):
    return {"dimensionHeaders": [{"name": d} for d in dimensions],
            "metricHeaders": [{"name": m} for m in traffic.METRICS],
            "rows": [{"dimensionValues": [{"value": v} for v in dims],
                      "metricValues": [{"value": str(v)} for v in values]} for dims, values in rows],
            "rowCount": len(rows) if count is None else count,
            "metadata": {"timeZone": "Asia/Hong_Kong"}}


class PartnerTrafficTests(unittest.TestCase):
    def test_page_scope_excludes_unrelated_partner_words_and_localhost(self):
        pattern = traffic.SCOPES["recruitment"]["pattern"]
        for path in ("/partners", "/de/partners", "/fr/partners/", "/zh-CN/partners"):
            self.assertRegex(path, pattern)
        for path in ("/partner", "/pages/partner-program", "/lifestyle/gifts-for-partners"):
            self.assertIsNone(re.fullmatch(pattern, path))
        self.assertRegex("//news/partners/post", traffic.SCOPES["content"]["pattern"])
        filt = json.dumps(traffic.scope_filter("recruitment"))
        self.assertIn('"hostName"', filt)
        self.assertIn('"vertu.com"', filt)
        self.assertNotIn("127.0.0.1", filt)

    def test_explicit_qa_is_excluded_without_subtracting_user_counts(self):
        clean = traffic.scope_filter("recruitment")
        self.assertIn({"notExpression": traffic.qa_filter()}, clean["andGroup"]["expressions"])
        raw = traffic.scope_filter("recruitment", include_qa=True)
        self.assertNotIn("notExpression", json.dumps(raw))
        self.assertIn("codex_prod_canary", json.dumps(traffic.qa_filter()))
        self.assertNotIn("feishu", json.dumps(clean))

    def test_pagination_preserves_rows_and_request_provenance(self):
        pages = [response(("pagePath",), [(('/partners',), (4, 3, 2, 1))], 2),
                 response(("pagePath",), [(('/de/partners',), (2, 2, 2, 1))], 2)]
        with patch.object(ga4, "_post", side_effect=pages) as post:
            result = traffic.query("test-token", "123", "2026-10-01", "2026-10-02",
                                   traffic.scope_filter("recruitment"), ["pagePath"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(json.loads(post.call_args_list[1].args[1])["offset"], "1")
        self.assertEqual(result["rows"][0]["activeUsers"], 2)
        self.assertNotIn("test-token", json.dumps(result))
        self.assertEqual(result["requests"][0]["dateRanges"][0]["endDate"], "2026-10-02")

    def test_missing_rows_stay_unknown_and_truncated_page_is_rejected(self):
        self.assertIsNone(traffic.summary({"rows": []})["sessions"])
        self.assertEqual(traffic.summary({"rows": [dict.fromkeys(traffic.METRICS, 0)]})["sessions"], 0)
        with patch.object(ga4, "_post", return_value=response(("date",), [], 3)):
            with self.assertRaises(ga4.Ga4Error):
                traffic.query("test", "123", "2026-10-01", "2026-10-02", {}, ["date"])

    def test_totals_are_queried_separately_from_nonadditive_page_users(self):
        def fake(token, prop, start, end, filt, dimensions):
            values = dict(zip(traffic.METRICS, (12, 8, 5, 4)))
            rows = [dict(values, **{d: "test" for d in dimensions})]
            if dimensions == ["pagePath"]:
                rows *= 2
            return {"rows": rows, "row_count": len(rows), "time_zone": "Asia/Hong_Kong",
                    "quality": [], "requests": [], "responses": []}
        with patch.object(ga4, "_service_account", return_value={"type": "service_account"}), \
                patch.object(ga4, "_property_id", return_value="123"), \
                patch.object(ga4, "_access_token", return_value="test-token"), \
                patch.object(traffic, "query", side_effect=fake):
            result = traffic.collect(28, end_date="2026-10-26")
        self.assertEqual(result["route"], 5)
        self.assertEqual(result["scopes"]["recruitment"]["summary"]["activeUsers"], 5)
        self.assertEqual(result["period"]["start_date"], "2026-09-29")
        self.assertTrue(result["test_traffic_excluded"])
        self.assertEqual(result["scopes"]["recruitment"]["raw_summary"]["activeUsers"], 5)
        self.assertEqual(result["scopes"]["recruitment"]["excluded_qa"]["activeUsers"], 5)
        self.assertNotIn("test-token", json.dumps(result))
        self.assertNotIn("revenue", result)

    def test_snapshot_uses_business_period_and_fetch_time_not_file_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traffic.json"
            old = {"schema_version": 1, "route": 5, "source": "GA4 Data API",
                   "test_traffic_excluded": True,
                   "fetched_at": "2026-10-01T00:00:00Z", "days": 28,
                   "period": {"start_date": "2026-09-03", "end_date": "2026-09-30",
                              "time_zone": "Asia/Hong_Kong"}, "scopes": {"recruitment": {}, "content": {}}}
            path.write_text(json.dumps(old), encoding="utf-8")
            with patch.dict(os.environ, {traffic.SNAPSHOT_ENV: str(path)}):
                result = traffic.briefing()
                self.assertTrue(result["stale"])
                self.assertEqual(result["period"]["end_date"], "2026-09-30")
                with self.assertRaises(ga4.Ga4Error):
                    traffic.briefing(7)

    def test_failed_refresh_preserves_original_snapshot_and_invalid_cache_can_refresh(self):
        cached = {"period": {"end_date": "2026-09-30"}, "stale": False}
        with patch.object(traffic, "_cached", return_value=cached), \
                patch.object(traffic, "collect", side_effect=ga4.Ga4Error("network failed")):
            result = traffic.briefing(force=True)
        self.assertTrue(result["stale"])
        self.assertEqual(result["period"], cached["period"])
        with patch.object(traffic, "_cached", side_effect=ga4.Ga4Error("old cache")), \
                patch.object(traffic, "collect", return_value={"fresh": True}), \
                patch.dict(os.environ, {traffic.SNAPSHOT_ENV: ""}):
            self.assertTrue(traffic.briefing(force=True)["fresh"])

    def test_invalid_counts_and_quality_flags_are_not_silently_accepted(self):
        for value in (None, "", "NaN", "-1", "1.5", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ga4.Ga4Error):
                traffic._integer(value)
        raw = response((), [((), (4, 3, 2, 1))])
        raw["metadata"]["subjectToThresholding"] = True
        with patch.object(ga4, "_post", return_value=raw):
            result = traffic.query("test", "123", "2026-10-01", "2026-10-02", {}, [])
        self.assertIn("subjectToThresholding", result["quality"])

    def test_authentication_cannot_send_assertion_to_other_token_host(self):
        with patch.object(ga4, "_post") as post:
            with self.assertRaises(ga4.Ga4Error):
                ga4._access_token({"type": "service_account", "token_uri": "https://example.invalid/token"})
        post.assert_not_called()

    def test_api_requires_manager_and_validates_days_before_query(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth.deps import get_current_user
        from app.growth.router import router

        app = FastAPI()
        app.include_router(router)
        user = SimpleNamespace(role="sales")
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client, \
                patch.object(ga4, "configured", return_value=True), \
                patch.object(traffic, "briefing", return_value={"source": "GA4 Data API"}) as fetch:
            endpoint = "/api/growth/seo/partner-traffic"
            self.assertEqual(client.get(endpoint).status_code, 403)
            fetch.assert_not_called()
            user.role = "manager"
            self.assertEqual(client.get(endpoint + "?days=0").status_code, 422)
            self.assertEqual(client.get(endpoint + "?days=91").status_code, 422)
            fetch.assert_not_called()
            self.assertEqual(client.get(endpoint + "?days=7&refresh=true").status_code, 200)
            fetch.assert_called_once_with(7, force=True)


if __name__ == "__main__":
    unittest.main()
