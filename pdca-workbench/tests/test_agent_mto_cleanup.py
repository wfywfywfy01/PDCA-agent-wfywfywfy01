# -*- coding: utf-8 -*-
"""MTO 图片下载残留隔日清理 + MTO 明细核对口径测试。"""
from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.mto_ocr import cleanup_temp_files


class TempCleanupTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = TemporaryDirectory()
        # tempfile.gettempdir() 会缓存首次结果，必须直接改 tempfile.tempdir。
        self.old_tempdir = tempfile.tempdir
        tempfile.tempdir = self.tmp.name

    def tearDown(self):
        import tempfile

        tempfile.tempdir = self.old_tempdir
        self.tmp.cleanup()

    def _make_stale_dir(self, name: str, age_hours: float) -> Path:
        path = Path(self.tmp.name) / name
        path.mkdir()
        (path / "shot.bin").write_bytes(b"x" * 1024)
        old = time.time() - age_hours * 3600
        os.utime(path / "shot.bin", (old, old))
        os.utime(path, (old, old))
        return path

    def test_removes_only_stale_mto_dirs(self):
        stale = self._make_stale_dir("mto-ocr-old", 30)
        fresh = self._make_stale_dir("mto-ocr-fresh", 1)
        other = Path(self.tmp.name) / "unrelated-dir"
        other.mkdir()
        os.utime(other, (time.time() - 999 * 3600,) * 2)
        result = cleanup_temp_files(24)
        self.assertEqual(result["removed"], 1)
        self.assertGreater(result["freed_bytes"], 0)
        self.assertFalse(stale.exists(), "隔日残留目录应被清理")
        self.assertTrue(fresh.exists(), "当天目录不能删")
        self.assertTrue(other.exists(), "非 mto-ocr- 前缀目录绝不触碰")

    def test_nothing_to_clean(self):
        self._make_stale_dir("mto-ocr-fresh", 0.5)
        result = cleanup_temp_files(24)
        self.assertEqual(result["removed"], 0)
        self.assertEqual(result["freed_bytes"], 0)


class _FakeOwner:
    display = "于冰"
    group = "于冰业绩达标群"
    follow_channel_id = "channel-yubing"
    im_user_id = 13063


class MtoDetailTests(unittest.TestCase):
    def test_detail_rows_and_summary(self):
        from app.agents import mto_vision_service

        file_names = ["2.webp", "3.webp", "4.webp", "1.webp"]
        quotes = [
            {"model": "Vertu Quantum", "usd": 45022.0, "wan": 32.0, "qualifies": True,
             "delivery": "2026-11-07", "target_customer": "", "raw_ok": True},
            {"model": "Vertu AlphaFold", "usd": 89180.0, "wan": 63.3, "qualifies": True,
             "delivery": "2026-11-27", "target_customer": "", "raw_ok": True},
            {"model": "Vertu Signature S+", "usd": 20010.0, "wan": 14.2, "qualifies": False,
             "delivery": "2026-09-20", "target_customer": "Bai Geng", "raw_ok": True},
            {"model": "VERTU MTO", "usd": 81868.0, "wan": 58.1, "qualifies": True,
             "delivery": "2026-11-07", "target_customer": "", "raw_ok": True},
        ]
        with patch.dict(mto_vision_service._cache, {}, clear=True), patch(
            "app.duzhan_ledger.OWNERS", (_FakeOwner(),)
        ), patch(
            "app.duzhan_ledger.fetch_channel_history", return_value=[]
        ), patch(
            "app.duzhan_ledger.messages_on_day", return_value=[]
        ), patch(
            "app.duzhan_ledger.parse_mto_images", return_value=(4, file_names)
        ), patch(
            "app.mto_ocr.review_mto_images", return_value=(3, [], quotes)
        ):
            result = mto_vision_service.review_owner_detail("于冰", "2026-09-18")
        self.assertEqual(result["images"], 4)
        self.assertEqual(result["qualified"], 3)
        self.assertEqual(result["under_threshold"], 1)
        self.assertEqual(result["unread"], 0)
        self.assertFalse(result["goal_met"], "4 款目标需 4 款达标")
        self.assertEqual(result["rows"][2]["verdict"], "未满30万")
        self.assertEqual(result["rows"][2]["customer"], "Bai Geng")
        self.assertEqual(result["rows"][0]["file"], "2.webp")

    def test_detail_unknown_owner(self):
        from app.agents import mto_vision_service

        with patch("app.duzhan_ledger.OWNERS", (_FakeOwner(),)):
            result = mto_vision_service.review_owner_detail("查无此人", "2026-09-18")
        self.assertIn("注册表", result.get("error", ""))


class CleanupJobRegistrationTests(unittest.TestCase):
    def test_daily_cleanup_job_registered(self):
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
            mto_temp_cleanup_enabled=True,
        )
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with patch.object(scheduler_jobs, "get_settings", return_value=settings), patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        jobs = [kwargs for _, _, kwargs in scheduler.jobs if kwargs["id"] == "mto_temp_cleanup"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["hour"], 3)
        self.assertEqual(jobs[0]["minute"], 30)


if __name__ == "__main__":
    unittest.main()
