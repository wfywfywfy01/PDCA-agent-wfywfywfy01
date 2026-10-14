# -*- coding: utf-8 -*-
"""P0 档位健康检查测试：Asia/Shanghai 与 Europe/Paris 双时区 + 缺快照场景。"""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlmodel import Session, SQLModel, create_engine

from app.agents.models import AgentEvent  # noqa: F401 - register table before create_all
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
        self.patch_code_source = patch("app.duzhan_admin.runtime.using_db", return_value=False)
        self.patch_code_source.start()
        self.notify_mock = MagicMock()
        # flow_controller 模块级导入 notify，patch 使用方模块。
        self.patch_notify = patch("app.agents.flow_controller.notify", self.notify_mock)
        self.patch_notify.start()

    def tearDown(self):
        self.patch_code_source.stop()
        self.patch_notify.stop()
        self.patch_slot.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def _fake_slot_path(self, tz_name, day, hour, key="", minute=0):
        slug = tz_name.lower().replace("/", "_")
        clock = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
        suffix = f"_{key}" if key else ""
        return self.slots_dir / f"{slug}_{day}_{clock}{suffix}.json"

    def _write_slot(self, tz_name, day, hour, prepared_iso, groups=4, minute=0):
        path = self._fake_slot_path(tz_name, day, hour, minute=minute)
        path.write_text(json.dumps({
            "tz": tz_name,
            "hour": hour,
            "minute": minute,
            "day": day,
            "prepared_at": prepared_iso,
            "idempotency_key": "duzhan-x",
            "ledger": {"people": []},
            "messages": {str(i): "m" for i in range(groups)},
        }, ensure_ascii=False), encoding="utf-8")

    def test_today_future_slot_is_pending_not_failed(self):
        now = datetime(2026, 9, 17, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        settings = SimpleNamespace(
            duzhan_enabled=True,
            ctob_enabled=False,
            duzhan_times=["10:00", "15:00"],
            agent_healthcheck_delay_minutes=5,
        )
        with patch.object(flow_controller, "get_settings", return_value=settings), patch.object(
            flow_controller, "cron_timezones", return_value=["Asia/Shanghai"]
        ), patch.object(
            flow_controller, "_health_hours", return_value=[10, 15],
        ), patch.object(flow_controller, "check_slot_health") as check:
            reports = flow_controller.all_slot_health_today("2026-09-17", now=now)
        self.assertEqual([row["state"] for row in reports], ["pending", "pending"])
        self.assertTrue(all(row["ok"] is None for row in reports))
        check.assert_not_called()

    def test_configured_grace_period_controls_pending_state(self):
        day = "2026-09-17"
        settings = SimpleNamespace(duzhan_times=["10:00"], agent_healthcheck_delay_minutes=15)
        with patch.object(flow_controller, "get_settings", return_value=settings), patch.object(
            flow_controller, "cron_timezones", return_value=["Asia/Shanghai"]
        ), patch.object(flow_controller, "_health_hours", return_value=[10]), patch.object(
            flow_controller, "_health_channels", return_value=["g1"]
        ), patch.object(flow_controller, "check_slot_health", return_value={
            "date": day, "timezone": "Asia/Shanghai", "hour": "10:00", "ok": True,
            "problems": [], "checked_at": "2026-09-17T10:15:00+08:00",
        }) as check:
            before = flow_controller.all_slot_health_today(
                day, now=datetime(2026, 9, 17, 10, 14, tzinfo=ZoneInfo("Asia/Shanghai"))
            )
            after = flow_controller.all_slot_health_today(
                day, now=datetime(2026, 9, 17, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
            )
        self.assertEqual(before[0]["state"], "pending")
        self.assertEqual(after[0]["state"], "passed")
        check.assert_called_once()

    def test_shared_slot_is_unknown_not_false_green_for_limited_manager(self):
        report = {
            "date": "2026-09-17", "timezone": "Asia/Shanghai", "hour": "10:00",
            "ok": True, "state": "passed", "problems": [],
            "checked_at": "2026-09-17T10:15:00+08:00", "channel_ids": ["mine", "other"],
        }
        scoped = flow_controller.scoped_slot_health([report], {"mine"})
        self.assertEqual(len(scoped), 1)
        self.assertIsNone(scoped[0]["ok"])
        self.assertEqual(scoped[0]["state"], "partial")
        self.assertNotIn("channel_ids", scoped[0])
        self.assertEqual(flow_controller.scoped_slot_health([report], {"unrelated"}), [])

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

    def test_cross_midnight_custom_slot_all_green(self):
        day = "2026-09-17"
        self._write_slot(
            "Asia/Shanghai", day, 0,
            datetime(2026, 9, 16, 23, 50, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            minute=5,
        )
        bucket = "Asia/Shanghai:0005:2026-09-17"
        _insert_run(self.engine, "duzhan_collect", bucket, "sent")
        _insert_run(self.engine, "duzhan", bucket, "sent")
        report = flow_controller.check_slot_health("Asia/Shanghai", 0, day, minute=5)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["slot"], "00:05")

    def test_db_slot_uses_group_snapshot_and_shared_run_names(self):
        day = "2026-09-17"
        channel_id = "11111111-1111-4111-8111-111111111111"
        bucket = f"Asia/Shanghai:10:{day}"
        slot = {
            "day": day, "hour": 10,
            "prepared_at": datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            "messages": {channel_id: "m"},
        }
        _insert_run(self.engine, "duzhan_collect:db:Asia/Shanghai", bucket, "sent")
        _insert_run(self.engine, "duzhan_push:db:Asia/Shanghai", bucket, "sent")
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.duzhan_admin.runtime.duzhan_agents", return_value=[
                 (object(), SimpleNamespace(channel_id=channel_id, tz="Asia/Shanghai"))
             ]), \
             patch("app.duzhan_admin.runtime.slots_of", return_value=[10]), \
             patch("app.duzhan_admin.runtime.slot_times_of", return_value=["10:00"]), \
             patch("app.agents.flow_controller.load_prepared", return_value=slot) as load:
            self.assertEqual(flow_controller._health_hours("Asia/Shanghai", ["20:00"]), [10])
            report = flow_controller.check_slot_health("Asia/Shanghai", 10, day)
        self.assertTrue(report["ok"], report["problems"])
        load.assert_called_once_with("Asia/Shanghai", 10, day, channel_id[:8])

    def test_db_health_keeps_same_hour_custom_slots_separate(self):
        day = "2026-09-17"
        exact = SimpleNamespace(slots=["09:00"])
        custom = SimpleNamespace(slots=["09:35"])
        exact_group = SimpleNamespace(
            channel_id="11111111-1111-4111-8111-111111111111", tz="Asia/Shanghai",
        )
        custom_group = SimpleNamespace(
            channel_id="22222222-2222-4222-8222-222222222222", tz="Asia/Shanghai",
        )
        bucket = f"Asia/Shanghai:09:{day}"
        _insert_run(self.engine, "duzhan_collect:db:Asia/Shanghai", bucket, "sent")
        _insert_run(self.engine, "duzhan_push:db:Asia/Shanghai", bucket, "sent")
        slot = {
            "day": day, "hour": 9, "minute": 0,
            "prepared_at": datetime(2026, 9, 17, 8, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            "messages": {exact_group.channel_id: "m"},
        }
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.duzhan_admin.runtime.duzhan_agents", return_value=[
                 (exact, exact_group), (custom, custom_group),
             ]), \
             patch("app.duzhan_admin.runtime.slot_times_of", side_effect=lambda agent: agent.slots), \
             patch("app.agents.flow_controller.load_prepared", return_value=slot) as load:
            report = flow_controller.check_slot_health("Asia/Shanghai", 9, day)
        self.assertTrue(report["ok"], report["problems"])
        load.assert_called_once_with("Asia/Shanghai", 9, day, exact_group.channel_id[:8])

    def test_db_mode_accepts_prior_code_slot_after_cutover(self):
        from app.duzhan import GROUPS

        day = "2026-09-17"
        bucket = f"Asia/Shanghai:10:{day}"
        _insert_run(self.engine, "duzhan_collect", bucket, "sent")
        _insert_run(self.engine, "duzhan", bucket, "sent")
        legacy_count = sum(group.tz == "Asia/Shanghai" for group in GROUPS)
        slot = {
            "day": day, "hour": 10,
            "prepared_at": datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            "messages": {str(i): "m" for i in range(legacy_count)},
        }
        group = SimpleNamespace(channel_id="11111111-1111-4111-8111-111111111111", tz="Asia/Shanghai")
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.duzhan_admin.runtime.duzhan_agents", return_value=[(object(), group)]), \
             patch("app.duzhan_admin.runtime.slots_of", return_value=[10]), \
             patch("app.duzhan_admin.runtime.slot_times_of", return_value=["10:00"]), \
             patch("app.agents.flow_controller.load_prepared", side_effect=lambda *_args: slot if len(_args) == 3 else None) as load:
            report = flow_controller.check_slot_health("Asia/Shanghai", 10, day, alert=False)
        self.assertTrue(report["ok"], report["problems"])
        load.assert_any_call("Asia/Shanghai", 10, day)

    def test_db_failure_is_not_hidden_by_prior_code_run(self):
        day = "2026-09-17"
        bucket = f"Asia/Shanghai:10:{day}"
        _insert_run(self.engine, "duzhan_collect:db:Asia/Shanghai", bucket, "failed")
        _insert_run(self.engine, "duzhan_collect", bucket, "sent")
        _insert_run(self.engine, "duzhan", bucket, "sent")
        group = SimpleNamespace(channel_id="11111111-1111-4111-8111-111111111111", tz="Asia/Shanghai")
        slot = {
            "day": day, "hour": 10,
            "prepared_at": datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")).isoformat(),
            "messages": {group.channel_id: "m"},
        }
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), \
             patch("app.duzhan_admin.runtime.duzhan_agents", return_value=[(object(), group)]), \
             patch("app.duzhan_admin.runtime.slots_of", return_value=[10]), \
             patch("app.duzhan_admin.runtime.slot_times_of", return_value=["10:00"]), \
             patch("app.agents.flow_controller.load_prepared", return_value=slot):
            report = flow_controller.check_slot_health("Asia/Shanghai", 10, day, alert=False)
        self.assertFalse(report["ok"])
        self.assertEqual([item["step"] for item in report["problems"]], ["collect_run"])

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
        self.patch_code_source = patch("app.duzhan_admin.runtime.using_db", return_value=False)
        self.patch_code_source.start()
        self.notify_mock = MagicMock()
        self.patch_notify = patch("app.agents.flow_controller.notify", self.notify_mock)
        self.patch_notify.start()
        settings_stub = MagicMock()
        settings_stub.duzhan_times = ["10:00", "15:00", "20:00"]
        settings_stub.agent_healthcheck_delay_minutes = 5
        self.patch_settings = patch(
            "app.agents.flow_controller.get_settings", return_value=settings_stub
        )
        self.patch_settings.start()

    def tearDown(self):
        self.patch_code_source.stop()
        self.patch_settings.stop()
        self.patch_notify.stop()
        self.patch_slot.stop()
        self.patch_events.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def _fake_slot_path(self, tz_name, day, hour, key="", minute=0):
        slug = tz_name.lower().replace("/", "_")
        clock = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
        suffix = f"_{key}" if key else ""
        return self.slots_dir / f"{slug}_{day}_{clock}{suffix}.json"

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

    def test_previous_day_cross_midnight_slot_is_checked(self):
        """23:59 档的宽限期跨到次日后，仍按前一天档位补扫。"""
        self.patch_settings.stop()
        settings_stub = MagicMock()
        settings_stub.duzhan_times = ["23:59"]
        settings_stub.agent_healthcheck_delay_minutes = 5
        self.patch_settings = patch(
            "app.agents.flow_controller.get_settings", return_value=settings_stub
        )
        self.patch_settings.start()

        now = datetime(2026, 9, 18, 0, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(flow_controller, "cron_timezones", return_value=["Asia/Shanghai"]), \
             patch.object(flow_controller, "_health_slots", return_value=["23:59"]):
            reports = flow_controller.run_health_checks_for(now=now)

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["date"], "2026-09-17")
        self.assertEqual(reports[0]["hour"], "23:59")

    def test_previous_day_slot_due_between_ticks_is_checked(self):
        """23:53 + 5 分钟宽限在 23:58 结束，下一次 00:00 扫描不能漏档。"""
        self.patch_settings.stop()
        settings_stub = MagicMock()
        settings_stub.duzhan_times = ["23:53"]
        settings_stub.agent_healthcheck_delay_minutes = 5
        self.patch_settings = patch(
            "app.agents.flow_controller.get_settings", return_value=settings_stub
        )
        self.patch_settings.start()

        now = datetime(2026, 9, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(flow_controller, "cron_timezones", return_value=["Asia/Shanghai"]), \
             patch.object(flow_controller, "_health_slots", return_value=["23:53"]):
            reports = flow_controller.run_health_checks_for(now=now)

        self.assertEqual([(item["date"], item["hour"]) for item in reports], [
            ("2026-09-17", "23:53"),
        ])

    def test_previous_day_missed_slot_is_checked_after_midnight_restart(self):
        """前一天 23:30 检查点停机，次日重启后仍补扫未记录的健康事件。"""
        self.patch_settings.stop()
        settings_stub = MagicMock()
        settings_stub.duzhan_times = ["23:30"]
        settings_stub.agent_healthcheck_delay_minutes = 5
        self.patch_settings = patch(
            "app.agents.flow_controller.get_settings", return_value=settings_stub
        )
        self.patch_settings.start()

        now = datetime(2026, 9, 18, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(flow_controller, "cron_timezones", return_value=["Asia/Shanghai"]), \
             patch.object(flow_controller, "_health_slots", return_value=["23:30"]):
            reports = flow_controller.run_health_checks_for(now=now)

        self.assertEqual([(item["date"], item["hour"]) for item in reports], [
            ("2026-09-17", "23:30"),
        ])


class CtobDbHealthTests(unittest.TestCase):
    def test_code_ctob_only_does_not_create_duzhan_health_targets(self):
        settings = SimpleNamespace(
            duzhan_enabled=False,
            ctob_enabled=True,
            duzhan_times=["10:00", "15:00", "20:00"],
        )
        with patch("app.duzhan_admin.runtime.using_db", return_value=False):
            self.assertEqual(flow_controller._health_targets(settings), [])

    def test_missing_ctob_db_slot_is_reported(self):
        agent = SimpleNamespace(slots=["09:35"])
        owner = SimpleNamespace(channel_id="11111111-1111-4111-8111-111111111111")
        with patch("app.duzhan_admin.runtime.using_db", return_value=True), patch(
            "app.duzhan_admin.runtime.follow_agents", return_value=[(agent, owner)],
        ), patch(
            "app.duzhan_admin.runtime.slot_times_of", side_effect=lambda row: row.slots,
        ), patch(
            "app.agents.flow_controller._scheduled_run_status", return_value={"found": False},
        ), patch(
            "app.ctob.load_snapshot", return_value={},
        ), patch.object(flow_controller, "notify") as notify:
            report = flow_controller.check_ctob_slot_health(
                9, "2026-09-17", minute=35,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(
            {item["step"] for item in report["problems"]},
            {"ctob_run", "ctob_snapshot"},
        )
        notify.assert_called_once()

    def test_ctob_only_db_slot_enters_catch_up_health_scan(self):
        agent = SimpleNamespace(slots=["09:35"])
        owner = SimpleNamespace(channel_id="11111111-1111-4111-8111-111111111111")
        settings = SimpleNamespace(
            duzhan_enabled=False,
            ctob_enabled=True,
            duzhan_times=["10:00", "15:00", "20:00"],
            agent_healthcheck_delay_minutes=5,
        )
        expected = {
            "date": "2026-09-17", "timezone": "Asia/Shanghai",
            "hour": "09:35", "slot": "09:35", "ok": False, "problems": [],
            "suggested_action": "", "checked_at": "now",
        }
        now = datetime(2026, 9, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(flow_controller, "get_settings", return_value=settings), patch.object(
            flow_controller, "cron_timezones", return_value=[],
        ), patch("app.duzhan_admin.runtime.using_db", return_value=True), patch(
            "app.duzhan_admin.runtime.follow_agents", return_value=[(agent, owner)],
        ), patch(
            "app.duzhan_admin.runtime.slot_times_of", side_effect=lambda row: row.slots,
        ), patch(
            "app.agents.events.write_event", return_value=True,
        ), patch.object(
            flow_controller, "check_ctob_slot_health", return_value=expected,
        ) as check:
            reports = flow_controller.run_health_checks_for(now=now)

        self.assertEqual(reports, [expected])
        check.assert_called_once_with(
            9, "2026-09-17", minute=35, now=now, alert=True,
        )


class BackupSlotRegistrationTests(unittest.TestCase):
    """补发兜底档（对齐核心日报 08:30/09:30 双触发模式）必须随督战开启而注册。"""

    def test_backup_jobs_registered_per_slot(self):
        from types import SimpleNamespace

        from app.scheduler import jobs as scheduler_jobs

        class RecordingScheduler:
            def __init__(self, **kwargs):
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
