"""Read-only runtime visibility and expired metadata recovery."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlmodel import Session, create_engine, select

from app.models.scheduled_job_run import ScheduledJobRun
from app.scheduler import run_ledger, jobs
from app import runtime_health


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        ScheduledJobRun.__table__.create(self.engine)
        self.settings = SimpleNamespace(scheduler_enabled=True, data_dir=Path("."), remote_db_from_host=False)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.engine.dispose()

    def seed(self, name, status, age_minutes, suffix=""):
        with Session(self.engine) as session:
            session.add(ScheduledJobRun(run_key=name+suffix, job_name=name, bucket=suffix,
                status=status, started_at=self.now-timedelta(minutes=age_minutes),
                finished_at=self.now-timedelta(minutes=age_minutes-1) if status != "sending" else None))
            session.commit()

    def test_expire_only_old_sending_without_triggering_messages(self):
        self.seed("old", "sending", 90)
        self.seed("fresh", "sending", 5)
        self.seed("complete", "sent", 90)
        with patch("app.scheduler.run_ledger.get_engine", return_value=self.engine), \
                patch("app.config.get_settings", return_value=self.settings):
            self.assertEqual(run_ledger.expire_stale_runs(), 1)
            self.assertEqual(run_ledger.expire_stale_runs(), 0)
        with Session(self.engine) as session:
            states = {r.job_name: r.status for r in session.exec(select(ScheduledJobRun)).all()}
        self.assertEqual(states, {"old": "failed", "fresh": "sending", "complete": "sent"})

    def test_expire_respects_local_remote_database_guard(self):
        self.settings.remote_db_from_host = True
        with patch("app.config.get_settings", return_value=self.settings), \
                patch.dict("os.environ", {"PDCA_ALLOW_REMOTE_DB": "0"}), \
                patch("app.scheduler.run_ledger.get_engine") as engine:
            self.assertEqual(run_ledger.expire_stale_runs(), 0)
        engine.assert_not_called()

    def test_latest_success_resolves_prior_failure_but_stale_is_visible(self):
        self.seed("ledger", "failed", 120, "-first")
        self.seed("ledger", "sent", 60, "-retry")
        self.seed("stale", "sending", 90)
        self.seed("failed", "failed", 40)
        with patch("app.runtime_health.get_engine", return_value=self.engine):
            result = runtime_health.job_status()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["stale_count"], 1)
        self.assertTrue(next(r for r in result["items"] if r["job_name"] == "ledger")["last_success_at"])

    def test_database_error_is_unknown_not_false_zero(self):
        with patch("app.runtime_health.get_engine", side_effect=RuntimeError("secret")):
            result = runtime_health.job_status()
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "unknown")
        self.assertIsNone(result["failed_count"])
        self.assertNotIn("secret", str(result))

    def test_old_run_just_expired_stays_failed_until_successful_retry(self):
        self.seed("ledger", "sending", 48 * 60, "-old")
        with patch("app.scheduler.run_ledger.get_engine", return_value=self.engine), \
                patch("app.config.get_settings", return_value=self.settings):
            self.assertEqual(run_ledger.expire_stale_runs(), 1)
        with patch("app.runtime_health.get_engine", return_value=self.engine):
            result = runtime_health.job_status()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_count"], 1)
        self.seed("ledger", "sent", 0, "-retry")
        with patch("app.runtime_health.get_engine", return_value=self.engine):
            result = runtime_health.job_status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["failed_count"], 0)

    def test_disk_low_space_and_probe_failure_are_explicit(self):
        with patch("app.runtime_health.shutil.disk_usage", return_value=SimpleNamespace(total=100, free=14)):
            result = runtime_health.disk_status(Path("."))
        self.assertFalse(result["ok"])
        self.assertEqual(result["free_percent"], 14)
        with patch("app.runtime_health.shutil.disk_usage", side_effect=OSError("secret")):
            result = runtime_health.disk_status(Path("."))
        self.assertEqual(result["state"], "unknown")
        self.assertNotIn("secret", str(result))


class LedgerJobTrackingTests(unittest.TestCase):
    def test_sync_job_records_success_and_failure(self):
        for code in (0, 1):
            with self.subTest(code=code), \
                    patch("app.scheduler.run_ledger.claim_run", return_value=True), \
                    patch("app.scheduler.run_ledger.finish_run") as finish, \
                    patch("app.scheduler.jobs.notify"), \
                    patch("subprocess.run", return_value=SimpleNamespace(returncode=code, stdout="done", stderr="")):
                jobs.todo_ledger_sync_job()
                self.assertEqual(finish.call_args.args[2], "sent" if code == 0 else "failed")

    def test_timeout_is_recorded_without_claiming_success(self):
        with patch("app.scheduler.run_ledger.claim_run", return_value=True), \
                patch("app.scheduler.run_ledger.finish_run") as finish, \
                patch("app.scheduler.jobs.notify"), \
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("python", 300)):
            jobs.todo_ledger_sync_job()
        self.assertEqual(finish.call_args.args[2], "failed")

    def test_sent_bucket_does_not_run_again(self):
        with patch("app.scheduler.run_ledger.claim_run", return_value=False), patch("subprocess.run") as run:
            jobs.todo_ledger_sync_job()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
