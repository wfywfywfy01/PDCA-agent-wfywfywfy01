"""A missed or busy business sync must not suppress the database backup."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler

from app.scheduler import jobs


class BackupSchedulerTests(unittest.TestCase):
    def test_backup_has_daily_schedule_isolated_executor_and_misfire_window(self):
        settings = SimpleNamespace(
            scheduler_enabled=True, sync_cron="0 6 * * *", daily_report_enabled=False,
            todo_remind_enabled=False, todo_remind_times=[], todo_group_notice_enabled=False,
            todo_group_channel_id="", todo_scoring_enabled=False, todo_ledger_sync_enabled=False,
            todo_brief_enabled=False, todo_okr_link_enabled=False,
        )
        with patch.object(jobs, "_scheduler", None), patch.object(jobs, "get_settings", return_value=settings), \
                patch.object(BackgroundScheduler, "start"):
            scheduler = jobs.start_scheduler()
        backup = scheduler.get_job("database_backup")
        self.assertIsNotNone(backup)
        self.assertIs(backup.func, jobs.database_backup_job)
        self.assertIsNot(backup.func, scheduler.get_job("daily_sync").func)
        self.assertEqual(str(backup.trigger), "cron[hour='2', minute='0']")
        self.assertEqual(backup.executor, "backup")
        self.assertEqual(backup.misfire_grace_time, 12 * 3600)
        self.assertEqual(backup.max_instances, 1)
        self.assertTrue(backup.coalesce)
        pool = scheduler._executors["backup"]
        self.addCleanup(pool.shutdown)
        self.assertEqual(pool._pool._max_workers, 1)
        # The wider grace is confined to backup: late business messages keep their policy.
        self.assertEqual(scheduler._job_defaults["misfire_grace_time"], 1)

    def test_daily_sync_success_or_failure_does_not_run_backup(self):
        for failure in (None, RuntimeError("sync unavailable")):
            with self.subTest(failure=failure), \
                    patch.object(jobs, "run_full_sync", return_value={}, side_effect=failure), \
                    patch.object(jobs, "backup_database") as backup, \
                    patch.object(jobs, "notify"), patch.object(jobs, "mark_sync"):
                jobs.daily_sync_job()
                backup.assert_not_called()

    def test_standalone_backup_does_not_wait_for_sync(self):
        with patch.object(jobs, "backup_database", return_value="unit-backup.sql") as backup, \
                patch.object(jobs, "run_full_sync") as sync, patch.object(jobs, "notify") as notify:
            jobs.database_backup_job()
        backup.assert_called_once_with()
        sync.assert_not_called()
        notify.assert_not_called()

    def test_failed_or_exceptional_backup_alerts_and_marks_failure(self):
        for failure in (None, RuntimeError("unit-backup-failed")):
            with self.subTest(failure=failure), patch.object(jobs, "_last_backup_error", ""), \
                    patch.object(jobs, "backup_database", return_value=None, side_effect=failure), \
                    patch.object(jobs, "notify") as notify:
                jobs.database_backup_job()
                self.assertTrue(jobs._last_backup_error)
                notify.assert_called_once_with("数据库备份失败", "请检查 pg_dump 配置与服务日志")


if __name__ == "__main__":
    unittest.main()
