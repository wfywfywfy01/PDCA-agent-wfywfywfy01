"""Monthly group rules persist independently and drive real quote qualification."""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.duzhan import GROUPS, render_brief
from app.duzhan_admin.router import require_admin
from app.duzhan_monthly_metrics import effective_metrics, recheck_row
from app.main import app


class MonthlyMetricsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)

        def sessions():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = sessions
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(role="admin", username="monthly-test")
        self.client = TestClient(app, base_url="https://testserver")
        self.headers = {"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"}
        self.group = GROUPS[0]
        self.url = "/api/duzhan-agents/monthly-metrics"
        self.payload = dict(channel_id=self.group.channel_id, month="2026-10", goal="amount",
                            sales_target_wan=250, mto_daily_count=2, mto_min_wan=20, version=0)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def read(self, **params):
        return self.client.get(self.url, params={"channel_id": self.group.channel_id, "month": "2026-10", **params})

    def save(self, **fields):
        return self.client.put(self.url, json={**self.payload, **fields}, headers=self.headers)

    def test_month_and_group_isolation_with_conflict_protection(self):
        initial = self.read().json()
        self.assertEqual(initial["metrics"]["sales_target_wan"], 200)
        self.assertEqual(initial["metrics"]["mto_daily_count"], 4)
        saved = self.save()
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["metrics"]["version"], 1)
        self.assertEqual(self.save(sales_target_wan=999).status_code, 409)
        self.assertEqual(self.save(month="2026-11", sales_target_wan=300).status_code, 200)
        self.assertEqual(self.read().json()["metrics"]["sales_target_wan"], 250)
        other = self.read(channel_id=GROUPS[1].channel_id).json()["metrics"]
        self.assertNotEqual(other["sales_target_wan"], 250)
        self.assertEqual(self.read().json()["saved_months"], ["2026-11", "2026-10"])
        self.assertIsNone(self.read(month="2026-12").json()["metrics"]["sales_target_wan"])

    def test_validation_and_admin_boundary(self):
        for fields in ({"month": "2026-13"}, {"month": "0000-10"}, {"mto_daily_count": 1.5},
                       {"mto_daily_count": -1}, {"mto_daily_count": 0}, {"mto_min_wan": 0}, {"mto_min_wan": "nan"},
                       {"sales_target_wan": -1}, {"sales_target_wan": None}):
            with self.subTest(fields=fields):
                self.assertEqual(self.save(**fields).status_code, 422)
        self.assertEqual(self.save(channel_id="not-a-group").status_code, 422)
        self.assertEqual(self.save(goal="break_zero", sales_target_wan=None).status_code, 200)
        self.assertEqual(self.client.put(self.url, json=self.payload,
                                        headers={"Origin": "https://outside.invalid"}).status_code, 403)
        del app.dependency_overrides[require_admin]
        self.assertIn(self.read().status_code, (401, 403))

    def test_saved_rules_drive_preview_and_reclassify_old_ocr_without_network(self):
        self.assertEqual(self.save().status_code, 200)
        with Session(self.engine) as session:
            metrics = effective_metrics(self.group.channel_id, "2026-10", session=session)
        quote = dict(wan=25, qualifies=False, raw_ok=True, model="Verified quote")
        row = dict(group=self.group.name, display="于冰", perf_arrived_wan=10, mto_count=0,
                   mto_quotes=[quote, dict(quote, wan=21)], history_ok=True, collections=[])
        checked = recheck_row(row, metrics)
        self.assertEqual(checked["mto_count"], 2)
        self.assertTrue(checked["mto_quotes"][0]["qualifies"])
        self.assertFalse(quote["qualifies"], "must not mutate the archived evidence")
        now = datetime(2026, 10, 21, 10, tzinfo=ZoneInfo(self.group.tz))
        with patch("app.duzhan_monthly_metrics.effective_metrics", return_value=metrics), \
             patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=True)), \
             patch("app.weekly_focus.items_for", return_value=[]), \
             patch("app.meeting_todos.items_for_group", return_value=[]):
            text = render_brief(self.group, 10, now, {"people": [row]})
            self.assertIn("250万", text)
            self.assertIn("每人2款，单款≥20万", text)
            evening = render_brief(self.group, 20, now.replace(hour=20), {"people": [row]})
            self.assertIn("已核达标2款", evening)
            self.assertIn("达标成员1/1", evening)
        self.assertIsNone(recheck_row({**row, "mto_count": None, "mto_quotes": []}, metrics)["mto_count"])
        self.assertIsNone(recheck_row({**row, "history_ok": False}, metrics)["mto_count"])

    def test_runtime_reads_saved_policy_and_fails_closed_when_database_is_unavailable(self):
        self.assertEqual(self.save().status_code, 200)
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.database.get_engine", return_value=self.engine):
            self.assertEqual(effective_metrics(self.group.channel_id, "2026-10")["mto_min_wan"], 20)
            from app.daily_report import _configured_sales_target

            total, _ = _configured_sales_target("2026-10")
            self.assertEqual(total, 1650 * 10000)
            self.assertEqual(self.save(month="2026-11").status_code, 200)
            with self.assertRaisesRegex(ValueError, "未设置"):
                _configured_sales_target("2026-11")
            with patch("app.database.get_engine", side_effect=RuntimeError("DB unavailable")):
                with self.assertRaisesRegex(RuntimeError, "DB unavailable"):
                    effective_metrics(self.group.channel_id, "2026-10")

    def test_policy_change_reuses_ocr_cache_and_keeps_task_only_exemption(self):
        import time
        from app.agents import mto_vision_service as vision
        from app.duzhan_admin.ai_rules import _cache_path
        from app.duzhan_blocks import Block

        self.assertEqual(self.save().status_code, 200)
        cached = dict(owner="于冰", day="2026-10-21", qualified=0, rows=[dict(wan=25, raw_ok=True,
                      qualifies=False, model="Real quote")], under_threshold=1, images=1, unread=0)
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.database.get_engine", return_value=self.engine), \
             patch.dict(vision._cache, {"detail:于冰:2026-10-21": (time.monotonic(), cached)}, clear=True), \
             patch("app.mto_ocr.review_mto_images", side_effect=AssertionError("must reuse OCR")):
            detail = vision.review_owner_detail("于冰", "2026-10-21")
            self.assertEqual(detail["qualified"], 1)
            self.assertEqual(detail["rows"][0]["verdict"], "达标")
            self.assertEqual(detail["goal"], 2)
            self.assertEqual(vision._owner_metrics("冯磊", "2026-10-21")["mto_daily_count"], 0)
            metrics = effective_metrics(self.group.channel_id, "2026-10")
            rule = Block("rule", {"mode": "ai", "prompt": "follow up"})
            first = _cache_path(1, "2026-10-21", 10, rule, metrics=metrics)
            self.assertEqual(self.save(version=1, mto_min_wan=40).status_code, 200)
            changed = effective_metrics(self.group.channel_id, "2026-10")
            self.assertNotEqual(first, _cache_path(1, "2026-10-21", 10, rule, metrics=changed))
            self.assertEqual(vision.review_owner_detail("于冰", "2026-10-21")["qualified"], 0)


if __name__ == "__main__":
    unittest.main()
