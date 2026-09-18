# -*- coding: utf-8 -*-
"""督战证据日报：定时任务注册 + 落盘（每天 07:30 一份，08:00 拉到桌面）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import evidence_report


def _ledger() -> dict:
    return {
        "day": "2026-09-18",
        "people": [
            {
                "group": "新人小组业绩达标群",
                "display": "邓琳莹",
                "target_wan": 20.0,
                "daily_target_wan": 0.67,
                "rolling_target_wan": 12.1,
                "target_gap_wan": -12.1,
                "target_ahead": False,
                "perf_arrived_wan": 0.0,
                "perf_slip": [
                    {"amount_text": "USD 45,022", "wan": 32.0, "snippet": "水单已回传", "source": "im:2026-09-18"}
                ],
                "perf_intent": [],
                "mto_count": 3,
                "mto_names": ["2.webp"],
                "mto_quotes": [
                    {
                        "file": "2.webp",
                        "model": "VERTU",
                        "usd": "45022",
                        "wan": 32.0,
                        "qualifies": True,
                        "verdict": "达标",
                        "delivery": "2026-11-07",
                        "customer": "Bai Geng",
                    }
                ],
                "wa_reached": 1,
                "hours_minutes": 163.0,
                "hours_band": "偏低",
                "daily_report": {"item_count": 4, "spent_hours": 8},
                "collections": [{"title": "索契水单", "amount": "$45,022", "progress": "催收", "status": "progress"}],
                "blockers": ["客户迟迟未回水单"],
                "evidence": ["$45,022"],
                "score": 100.0,
            }
        ],
        "red": [{"display": "邓琳莹", "score": 100.0, "combined_score": 100.0, "perf_score": None}],
        "black": [{"display": "江旭", "reason": "未报今日任务"}],
        "_raw_by_owner": {
            "邓琳莹": [
                {
                    "created_at": "2026-09-18T09:10:00Z",
                    "message_type": "text",
                    "body": "1. 触达名单30个 2. MTO高定图2款",
                }
            ]
        },
        "_images": {"邓琳莹": [{"name": "2.webp", "b64": None, "note": "下载失败"}]},
        "_elapsed": 1.0,
        "_bot_id": "bot",
    }


class EvidenceSaveTests(unittest.TestCase):
    def test_save_report_writes_html_and_json(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_dir = Path(tmp.name) / "exports" / "evidence"
        with mock.patch("app.evidence_report.collect", return_value=_ledger()):
            summary = evidence_report.save_report("2026-09-18", out_dir, image_limit=0)
        html_path = Path(summary["html"])
        self.assertTrue(html_path.exists())
        self.assertIn("督战证据_2026-09-18.html", str(html_path))
        text = html_path.read_text(encoding="utf-8")
        self.assertIn("督战证据日报 · 2026-09-18", text)
        self.assertIn("邓琳莹", text)
        self.assertIn("水单已回传", text)
        self.assertIn("2.webp", text)
        self.assertIn("复查要点", text)
        sidecar = json.loads((out_dir / "督战证据_2026-09-18.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["people"], 1)
        self.assertEqual(sidecar["day"], "2026-09-18")
        self.assertEqual(summary["messages"], 1)

    def test_report_is_read_only(self):
        """证据日报绝不能发消息（防回归）。"""
        source = Path(evidence_report.__file__).read_text(encoding="utf-8")
        for banned in ("push_duzhan_message", "push_vps_message", "im +send", "agent-notify"):
            self.assertNotIn(banned, source, banned + " 不应该出现在证据日报里")


class EvidenceRegistrationTests(unittest.TestCase):
    def _register(self, **over: object):
        from app.scheduler import jobs as scheduler_jobs

        class RecordingScheduler:
            def __init__(self):
                self.jobs = []

            def add_job(self, func, *args, **kwargs):
                self.jobs.append((func, args, kwargs))

            def start(self):
                return None

        base = {
            "scheduler_enabled": True,
            "sync_cron": "0 6 * * *",
            "daily_report_enabled": False,
            "todo_remind_enabled": False,
            "todo_remind_times": [],
            "todo_group_notice_enabled": False,
            "todo_group_channel_id": "",
            "todo_scoring_enabled": False,
            "todo_ledger_sync_enabled": False,
            "todo_brief_enabled": False,
            "todo_okr_link_enabled": False,
            "mto_temp_cleanup_enabled": False,
            "daily_digest_enabled": False,
            "evidence_report_enabled": True,
            "evidence_report_time": "07:30",
        }
        base.update(over)
        settings = SimpleNamespace(**base)
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with mock.patch.object(
                scheduler_jobs, "get_settings", return_value=settings
            ), mock.patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        return {
            kwargs["id"]: (kwargs["hour"], kwargs["minute"])
            for _, _, kwargs in scheduler.jobs
            if str(kwargs.get("id", "")).startswith("evidence_report")
        }

    def test_registered_at_0730(self):
        self.assertEqual(self._register()["evidence_report"], (7, 30))

    def test_daily_not_weekday_only(self):
        from app.scheduler import jobs as scheduler_jobs

        class RecordingScheduler:
            def __init__(self):
                self.jobs = []

            def add_job(self, func, *args, **kwargs):
                self.jobs.append((func, args, kwargs))

            def start(self):
                return None

        settings = SimpleNamespace(
            scheduler_enabled=True,
            sync_cron="0 6 * * *",
            daily_report_enabled=False,
            todo_remind_enabled=False,
            todo_remind_times=[],
            todo_group_notice_enabled=False,
            todo_group_channel_id="",
            todo_scoring_enabled=False,
            todo_ledger_sync_enabled=False,
            todo_brief_enabled=False,
            todo_okr_link_enabled=False,
            mto_temp_cleanup_enabled=False,
            daily_digest_enabled=False,
            evidence_report_enabled=True,
            evidence_report_time="07:30",
        )
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with mock.patch.object(
                scheduler_jobs, "get_settings", return_value=settings
            ), mock.patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        job = [
            kwargs for _, _, kwargs in scheduler.jobs if kwargs.get("id") == "evidence_report"
        ][0]
        self.assertEqual(job["day_of_week"], "mon-sun")

    def test_disabled_registers_nothing(self):
        self.assertEqual(self._register(evidence_report_enabled=False), {})


if __name__ == "__main__":
    unittest.main()