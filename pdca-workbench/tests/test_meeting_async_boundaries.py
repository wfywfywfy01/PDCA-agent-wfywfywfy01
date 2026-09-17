"""Meeting snapshot sync must not call asyncio.run inside request event loops."""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from app.admin import router as admin_router
from app.auth.models import User
from app.meeting import router as meeting_router
from app.models import sync as sync_module
from app.scheduler import jobs as scheduler_jobs


class MeetingAsyncBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_sync_runs_blocking_snapshot_work_off_event_loop(self):
        expected = {"date": "2026-09-16", "meetings": 3}
        with patch.object(admin_router, "run_full_sync", return_value=expected) as sync:
            result = await admin_router.trigger_sync("2026-09-16", None)
        self.assertEqual(result, expected)
        sync.assert_called_once_with("2026-09-16")

    async def test_dispatch_runs_legacy_bridge_and_snapshot_off_event_loop(self):
        request_thread = threading.get_ident()
        bridge_threads: list[int] = []
        snapshot_threads: list[int] = []

        def send(*_args):
            bridge_threads.append(threading.get_ident())
            return {"ok": True}

        def snapshot(*_args):
            snapshot_threads.append(threading.get_ident())
            return 1

        admin = User(username="admin", hashed_password="unused", role="admin")
        body = meeting_router.DispatchBody(
            date="2026-09-16",
            assignments=[{"owner": "何海文", "title": "发送报价"}],
        )
        with patch.object(meeting_router.bridge, "api_meeting_center_dispatch", side_effect=send), patch.object(
            sync_module, "sync_meetings", side_effect=snapshot,
        ):
            result = await meeting_router.dispatch(body, admin, MagicMock())
        self.assertTrue(result["ok"])
        self.assertNotEqual(bridge_threads, [request_thread])
        self.assertNotEqual(snapshot_threads, [request_thread])

    async def test_summary_returns_503_instead_of_fake_zero_when_source_missing(self):
        admin = User(username="admin", hashed_password="unused", role="admin")
        with patch.object(
            meeting_router,
            "_load_meetings",
            new=AsyncMock(return_value={"ok": False, "error": "Vemory 不可用", "summary": {}}),
        ):
            with self.assertRaises(HTTPException) as exc:
                await meeting_router.summary("2026-09-16", None, admin, MagicMock())
        self.assertEqual(exc.exception.status_code, 503)

    async def test_summary_keeps_snapshot_state_and_freshness(self):
        admin = User(username="admin", hashed_password="unused", role="admin")
        payload = {
            "ok": True,
            "summary": {"total": 1},
            "scope": "all",
            "state": "stale",
            "source": "meeting_records_snapshot",
            "warning": "Vemory 暂不可用",
            "snapshot_at": "2026-09-16T10:00:00",
        }
        with patch.object(meeting_router, "_load_meetings", new=AsyncMock(return_value=payload)):
            result = await meeting_router.summary("2026-09-16", None, admin, MagicMock())
        self.assertEqual(result["state"], "stale")
        self.assertEqual(result["snapshot_at"], "2026-09-16T10:00:00")


class MeetingSchedulerTests(unittest.TestCase):
    def test_snapshot_sync_is_registered_every_30_minutes_in_work_hours(self):
        class RecordingScheduler:
            def __init__(self):
                self.jobs = []

            def add_job(self, func, *args, **kwargs):
                self.jobs.append((func, kwargs))

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
        )
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with patch.object(scheduler_jobs, "get_settings", return_value=settings), patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler,
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        job = next(kwargs for _, kwargs in scheduler.jobs if kwargs["id"] == "meeting_snapshot_sync")
        self.assertEqual(job["hour"], "7-22")
        self.assertEqual(job["minute"], "*/30")
        self.assertTrue(job["coalesce"])


if __name__ == "__main__":
    unittest.main()
