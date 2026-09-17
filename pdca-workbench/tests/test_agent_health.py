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


if __name__ == "__main__":
    unittest.main()
