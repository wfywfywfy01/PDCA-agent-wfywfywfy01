"""Missing analytics must not become evidence of zero traffic."""
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.growth import ga4, service


class GrowthAnalyticsTests(unittest.TestCase):
    def test_missing_topic_is_unknown_but_reported_zero_is_preserved(self):
        topics = [
            {"title": name, "url": f"https://vertu.com/news/partners/{name}",
             "path": f"/news/partners/{name}"}
            for name in ("missing", "zero")
        ]
        row = {"page": topics[1]["path"], "views": 0, "sessions": 0,
               "users": 0, "engRate": 0, "keyEvents": 0}
        with patch.object(ga4, "content_rows", return_value=[]), \
                patch.object(ga4, "path_rows", return_value=[row]), \
                patch.object(ga4, "load_topics", return_value=topics):
            result = ga4._live_briefing()
        self.assertIn(topics[0]["url"] + "\tN/A\tN/A\tN/A", result["table"])
        self.assertIn(topics[1]["url"] + "\t0\t0\t0", result["table"])
        self.assertIn("100", result["table"])
        self.assertTrue(result["fetched_at"].endswith("Z"))

    def test_legacy_snapshot_cannot_reintroduce_false_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "snapshot.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"table": "legacy topic\turl\t0\t0\t", "days": 28}, fh)
            with patch.dict(os.environ, {"PDCA_GROWTH_GA4_SNAPSHOT": path}), \
                    patch.object(ga4, "_live_briefing") as live:
                with self.assertRaisesRegex(ga4.Ga4Error, "快照"):
                    ga4.briefing()
                live.assert_not_called()

    def test_snapshot_only_deployment_can_supply_review_data(self):
        session = Mock()
        session.exec.return_value.one.return_value = 0
        with patch.dict(os.environ, {"PDCA_GROWTH_GA4_SNAPSHOT": "snapshot.json"}), \
                patch.object(ga4, "configured", return_value=False), \
                patch.object(ga4, "briefing", return_value={"table": "verified snapshot", "stale": True,
                    "fetched_at": "2026-10-22T00:00:00Z"}) as briefing, \
                patch("app.growth.fetcher.list_posts", return_value=[]), \
                patch.object(service, "_llm", return_value='{"variants": []}') as llm:
            service.seo_review(session, ideas=1)
        briefing.assert_called_once()
        prompt = llm.call_args.args[0][1]["content"]
        self.assertIn("verified snapshot", prompt)
        self.assertIn("2026-10-22T00:00:00Z", prompt)
        self.assertIn("snapshot", prompt.lower())

    def test_unavailable_traffic_blocks_traffic_driven_analysis(self):
        session = Mock()
        session.exec.return_value.one.return_value = 0
        with patch.object(ga4, "configured", return_value=True), \
                patch.object(ga4, "briefing", side_effect=ga4.Ga4Error("offline")), \
                patch("app.growth.fetcher.list_posts", return_value=[]), \
                patch.object(service, "_llm", return_value='{"variants": []}') as llm:
            with self.assertRaises(ga4.Ga4Error):
                service.seo_review(session, ideas=1)
        llm.assert_not_called()

    def test_error_page_is_not_audited_as_article(self):
        session = Mock()
        session.exec.return_value.one.return_value = 0
        with patch("app.growth.fetcher.fetch_post", return_value={
                "status": 404, "title": "Not found", "meta": "", "words": 2, "text": "Not found"}), \
                patch.object(service, "_llm", return_value='{"variants": []}') as llm:
            with self.assertRaisesRegex(ValueError, "404"):
                service.seo_review(session, urls=["https://vertu.com/missing"], table="page\tviews")
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
