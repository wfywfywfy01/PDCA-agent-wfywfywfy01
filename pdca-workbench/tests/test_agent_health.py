# -*- coding: utf-8 -*-
"""P0 档位健康检查测试：Asia/Shanghai 与 Europe/Paris 双时区 + 缺快照场景。"""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlmodel import Session, SQLModel, create_engine

from app.models.scheduled_job_run import ScheduledJobRun
from app.agents import flow_controller


def _mk_engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def _insert_run(engine, job_name: str, bucket: str, status: str):
    from datetime import datetime as dt, timezone as tz

    with Session(engine) as session:
        session.add(ScheduledJobRun(
            run_key=f"{job_name}:{bucket}", job_name=job_name, bucket=bucket,
            status=status, started_at=dt.now(tz.utc),
            finished_at=dt.now(tz.utc) if status != "sending" else None,
        ))
        session.commit()


class SlotHealthTests(unittest.TestCase):
    """健康检查：只读、不补发、缺快照告警。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.slots_dir = Path(self.tmp.name) / "slots"
        self.slots_dir.mkdir()
        self.engine = _mk_engine()
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_slot = patch(
            "app.duzhan._slot_path",
            side_effect=self._fake_slot_path,
        )
        self.patch_slot.start()
        self.notify_mock = MagicMock()
        # flow_controller 模块级导入 notify，patch 使用方模块。
        self.patch_notify = patch("app.agents.flow_controller.notify", self.notify_mock)
        self.patch_notify.start()

    def tearDown(self):
        self.patch_notify.stop()
        self.patch_slot.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def _fake_slot_path(self, tz_name, day, hour):
        slug = tz_name.lower().replace("/", "_")
        return self.slots_dir / f"{slug}_{day}_{hour:02d}.json"

    def _write_slot(self, tz_name, day, hour, prepared_iso, groups=4):
        path = self._fake_slot_path(tz_name, day, hour)
        path.write_text(json.dumps({
            "tz": tz_name,
            "hour": hour,
            "day": day,
            "prepared_at": prepared_iso,
            "idempotency_key": "duzhan-x",
            "ledger": {"people": []},
            "messages": {str(i): "m" for i in range(groups)},
        }, ensure_ascii=False), encoding="utf-8")

    def test_shanghai_slot_all_green(self):
        day = "2026-09-17"
        self._write_slot(
            "Asia/Shanghai", day, 10,
            datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
        )
        _insert_run(self.engine, "duzhan_collect", "Asia/Shanghai:10:2026-09-17", "sent")
        _insert_run(self.engine, "duzhan", "Asia/Shanghai:10:2026-09-17", "sent")
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["timezone"], "Asia/Shanghai")
        self.assertFalse(self.notify_mock.called)

    def test_paris_slot_all_green(self):
        day = "2026-09-17"
        self._write_slot(
            "Europe/Paris", day, 15,
            datetime(2026, 9, 17, 14, 45, tzinfo=ZoneInfo("Europe/Paris")).isoformat(),
            groups=1,
        )
        _insert_run(self.engine, "duzhan_collect", "Europe/Paris:15:2026-09-17", "sent")
        _insert_run(self.engine, "duzhan", "Europe/Paris:15:2026-09-17", "sent")
        report = flow_controller.check_slot_health("Europe/Paris", 15, day)
        self.assertTrue(report["ok"], report["problems"])

    def test_missing_snapshot_alerts(self):
        """规格 17.3：9/17 10:00 快照缺失 -> 告警且不补发。"""
        day = "2026-09-17"
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertFalse(report["ok"])
        steps = {item["step"] for item in report["problems"]}
        self.assertIn("slot_snapshot", steps)
        self.assertIn("collect_run", steps)
        self.assertTrue(self.notify_mock.called)
        self.assertTrue(report["suggested_action"])

    def test_wrong_slot_snapshot_alerts(self):
        day = "2026-09-17"
        # prepared_at 属于 15:00 档却拿给 10:00 档检查
        self._write_slot(
            "Asia/Shanghai", day, 10,
            datetime(2026, 9, 17, 14, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
        )
        _insert_run(self.engine, "duzhan_collect", "Asia/Shanghai:10:2026-09-17", "sent")
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertFalse(report["ok"])
        self.assertTrue(any("prepared_at" in item["detail"] for item in report["problems"]))

    def test_group_count_mismatch(self):
        day = "2026-09-17"
        self._write_slot(
            "Asia/Shanghai", day, 10,
            datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            groups=2,  # 北京应有 4 个达标群
        )
        _insert_run(self.engine, "duzhan_collect", "Asia/Shanghai:10:2026-09-17", "sent")
        _insert_run(self.engine, "duzhan", "Asia/Shanghai:10:2026-09-17", "sent")
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertFalse(report["ok"])
        self.assertTrue(any("群消息" in item["detail"] for item in report["problems"]))

    def test_push_failed_alerts(self):
        day = "2026-09-17"
        self._write_slot(
            "Asia/Shanghai", day, 10,
            datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
        )
        _insert_run(self.engine, "duzhan_collect", "Asia/Shanghai:10:2026-09-17", "sent")
        _insert_run(self.engine, "duzhan", "Asia/Shanghai:10:2026-09-17", "failed")
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertFalse(report["ok"])
        steps = {item["step"] for item in report["problems"]}
        self.assertIn("push_run", steps)

    def test_alert_false_does_not_notify(self):
        """后台展示路径（alert=False）不触发告警。"""
        day = "2026-09-17"
        report = flow_controller.check_slot_health("Asia/Shanghai", 10, day, alert=False)
        self.assertFalse(report["ok"])
        self.assertFalse(self.notify_mock.called)


class HealthCatchUpTests(unittest.TestCase):
    """补扫：重启后当天已过档位也会被检查；每档只告警一次。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.slots_dir = Path(self.tmp.name) / "slots"
        self.slots_dir.mkdir()
        self.engine = _mk_engine()
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_events = patch("app.agents.events.get_engine", return_value=self.engine)
        self.patch_events.start()
        self.patch_slot = patch("app.duzhan._slot_path", side_effect=self._fake_slot_path)
        self.patch_slot.start()
        self.notify_mock = MagicMock()
        self.patch_notify = patch("app.agents.flow_controller.notify", self.notify_mock)
        self.patch_notify.start()
        settings_stub = MagicMock()
        settings_stub.duzhan_times = ["10:00", "15:00", "20:00"]
        self.patch_settings = patch(
            "app.agents.flow_controller.get_settings", return_value=settings_stub
        )
        self.patch_settings.start()

    def tearDown(self):
        self.patch_settings.stop()
        self.patch_notify.stop()
        self.patch_slot.stop()
        self.patch_events.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def _fake_slot_path(self, tz_name, day, hour):
        slug = tz_name.lower().replace("/", "_")
        return self.slots_dir / f"{slug}_{day}_{hour:02d}.json"

    def test_catch_up_checks_past_hour_after_restart(self):
        """11:00 时 10:00 档已过：补扫检查到且告警一次，重复 tick 不再告警。"""
        now = datetime(2026, 9, 17, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        reports = flow_controller.run_health_checks_for(now=now)
        checked = {item["hour"] for item in reports}
        self.assertIn("10:00", checked)
        self.assertTrue(self.notify_mock.called)
        # 同一档第二次 tick 被事件去重跳过
        self.notify_mock.reset_mock()
        reports2 = flow_controller.run_health_checks_for(now=now)
        self.assertFalse(self.notify_mock.called)
        self.assertEqual(reports2, [])

    def test_current_hour_within_first_5_minutes_skipped(self):
        """10:03 时当前档尚未到检查点（推送可能未完成），只补扫更早档位。"""
        now = datetime(2026, 9, 17, 10, 3, tzinfo=ZoneInfo("Asia/Shanghai"))
        reports = flow_controller.run_health_checks_for(now=now)
        self.assertEqual(reports, [])

    def test_future_hours_not_checked(self):
        now = datetime(2026, 9, 17, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        reports = flow_controller.run_health_checks_for(now=now)
        self.assertEqual(reports, [])


class BackupSlotRegistrationTests(unittest.TestCase):
    """补发兜底档（对齐核心日报 08:30/09:30 双触发模式）必须随督战开启而注册。"""

    def test_backup_jobs_registered_per_slot(self):
        from types import SimpleNamespace

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
            duzhan_enabled=True,
            duzhan_times=["10:00", "15:00", "20:00"],
            duzhan_lead_minutes=15,
            duzhan_reply_enabled=False,
            ctob_enabled=True,
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
        backup_ids = {
            kwargs["id"] for _, _, kwargs in scheduler.jobs
            if kwargs["id"].startswith("duzhan_backup_")
        }
        self.assertEqual(len(backup_ids), 6, f"两时区×三档应有 6 个兜底任务，实际 {sorted(backup_ids)}")
        self.assertIn("duzhan_backup_asia_shanghai_10", backup_ids)
        self.assertIn("duzhan_backup_europe_paris_20", backup_ids)
        ctob_backup = [
            kwargs for _, _, kwargs in scheduler.jobs if kwargs["id"] == "ctob_backup_2030"
        ]
        self.assertEqual(len(ctob_backup), 1)
        self.assertEqual(ctob_backup[0]["hour"], 20)
        self.assertEqual(ctob_backup[0]["minute"], 30)
        # 兜底任务与主任务共享同一函数与参数（claim_run 台账去重）
        shanghai_10_backup = next(
            kwargs for _, _, kwargs in scheduler.jobs
            if kwargs["id"] == "duzhan_backup_asia_shanghai_10"
        )
        shanghai_10_main = next(
            kwargs for _, _, kwargs in scheduler.jobs
            if kwargs["id"] == "duzhan_asia_shanghai_10"
        )
        self.assertEqual(shanghai_10_backup["args"], shanghai_10_main["args"])


if __name__ == "__main__":
    unittest.main()
