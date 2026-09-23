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


class SharedRecipientTests(unittest.TestCase):
    """一份收件人名单：PDCA_MGMT_HTML_USER_IDS 给所有早报 HTML 用。"""

    def test_feature_list_wins_over_shared(self):
        from app.im_files import resolve_user_ids

        settings = SimpleNamespace(mgmt_html_user_ids=[13365], evidence_report_user_ids=[1])
        self.assertEqual(resolve_user_ids(settings, "evidence_report_user_ids"), [1])

    def test_falls_back_to_shared_list(self):
        from app.im_files import resolve_user_ids

        settings = SimpleNamespace(mgmt_html_user_ids=[13365, 13102, 12564], evidence_report_user_ids=[])
        self.assertEqual(
            resolve_user_ids(settings, "evidence_report_user_ids"), [13365, 13102, 12564]
        )

    def test_deliver_uses_shared_list_when_not_passed(self):
        import tempfile

        from app.im_files import send_files

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        html = Path(tmp.name) / "督战证据_2026-09-18.html"
        html.write_text("<html>x</html>", encoding="utf-8")
        calls: list[list[str]] = []

        def fake_run(args, timeout=None):
            calls.append(args)
            return 0, "{}", ""

        shared = SimpleNamespace(
            duzhan_bot_app_id="vbot_duzhan",
            todo_bot_app_id="",
            mgmt_html_user_ids=[13365, 13102, 12564],
            evidence_report_user_ids=[],
        )
        with mock.patch("app.config.get_settings", return_value=shared), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            result = evidence_report.deliver_report(
                {"day": "2026-09-18", "html": str(html), "bytes": 10, "people": 1, "images": 0}
            )
        self.assertEqual(result["sent"], ["user:13365", "user:13102", "user:12564"])
        self.assertEqual(len(calls), 3)

    def test_deliver_prefers_group_over_private_ids(self):
        """配了 PDCA_MGMT_HTML_CHANNEL_ID 就只发群，不再私发（2026-09-23 用户要求）。"""
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        html = Path(tmp.name) / "督战证据_2026-09-18.html"
        html.write_text("<html>x</html>", encoding="utf-8")
        calls: list[list[str]] = []

        def fake_run(args, timeout=None):
            calls.append(args)
            return 0, "{}", ""

        shared = SimpleNamespace(
            duzhan_bot_app_id="vbot_duzhan",
            todo_bot_app_id="",
            mgmt_html_user_ids=[13365, 13102, 12564],
            mgmt_html_channel_id="chan-mgmt",
            evidence_report_user_ids=[],
        )
        with mock.patch("app.config.get_settings", return_value=shared), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            result = evidence_report.deliver_report(
                {"day": "2026-09-18", "html": str(html), "bytes": 10, "people": 1, "images": 0}
            )
        self.assertEqual(result["sent"], ["channel"])
        self.assertEqual(len(calls), 1, "只发群，不能再私发")
        self.assertIn("+send", calls[0])
        self.assertIn("chan-mgmt", calls[0])

    def test_send_files_skips_missing_html(self):
        from app.im_files import send_files

        result = send_files(html_path="D:/not-exist-xyz.html", user_ids=[13365])
        self.assertEqual(result["sent"], [])
        self.assertTrue(result["failed"])


class EvidenceDeliveryTests(unittest.TestCase):
    """交付环节：私聊发文件；不配群就绝不发群（老板 2026-09-19）。"""

    def _summary(self, tmp: str) -> dict:
        html_path = Path(tmp) / "督战证据_2026-09-18.html"
        html_path.write_text("<html>报告</html>", encoding="utf-8")
        html_path.with_suffix(".json").write_text("{}", encoding="utf-8")
        return {"day": "2026-09-18", "html": str(html_path), "bytes": 1234, "people": 3, "images": 2}

    def test_sends_to_configured_users_only(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls: list[list[str]] = []

        def fake_run(args, timeout=None):
            calls.append(args)
            return 0, "{}", ""

        bot_settings = SimpleNamespace(
            duzhan_bot_app_id="vbot_duzhan", todo_bot_app_id=""
        )
        with mock.patch("app.config.get_settings", return_value=bot_settings), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            result = evidence_report.deliver_report(self._summary(tmp.name), user_ids=[13365])
        self.assertEqual(result["sent"], ["user:13365"])
        self.assertEqual(result["failed"], [])
        args = calls[0]
        self.assertIn("+bot-send-user", args)
        self.assertIn("--attach", args)
        self.assertIn("file", args)
        self.assertNotIn("+send", args, "没配群就不许发群")

    def test_falls_back_to_account_identity_without_bot(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls: list[list[str]] = []

        def fake_run(args, timeout=None):
            calls.append(args)
            return 0, "{}", ""

        no_bot = SimpleNamespace(duzhan_bot_app_id="", todo_bot_app_id="")
        with mock.patch("app.config.get_settings", return_value=no_bot), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            result = evidence_report.deliver_report(self._summary(tmp.name), user_ids=[13365])
        self.assertEqual(result["sent"], ["user:13365"])
        self.assertIn("+send-user", calls[0])

    def test_no_recipients_no_send(self):
        """收件人与共享名单都为空 → 一条都不发（共享名单默认非空时另行覆盖）。"""
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        empty = SimpleNamespace(
            duzhan_bot_app_id="vbot", todo_bot_app_id="",
            mgmt_html_user_ids=[], evidence_report_user_ids=[],
        )
        with mock.patch("app.config.get_settings", return_value=empty), mock.patch(
            "app.vertu.client.run_vertu_sync"
        ) as run:
            result = evidence_report.deliver_report(self._summary(tmp.name))
        run.assert_not_called()
        self.assertEqual(result["sent"], [])

    def test_group_send_requires_explicit_channel(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls: list[list[str]] = []

        def fake_run(args, timeout=None):
            calls.append(args)
            return 0, "{}", ""

        no_users = SimpleNamespace(
            duzhan_bot_app_id="vbot", todo_bot_app_id="",
            mgmt_html_user_ids=[], evidence_report_user_ids=[],
        )
        with mock.patch("app.config.get_settings", return_value=no_users), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            result = evidence_report.deliver_report(
                self._summary(tmp.name), channel_id="7065d7ec-8b7a-4006-93ff-459d4d1671ad"
            )
        self.assertEqual(result["sent"], ["channel"])
        self.assertIn("--channel-id", calls[0])


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