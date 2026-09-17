# -*- coding: utf-8 -*-
"""流程控制器测试：采集/推送封装、事件落库、C转B 封装、幂等语义。"""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlmodel import Session, SQLModel, create_engine

from app.agents import flow_controller
from app.agents.events import write_event
from app.agents.models import AgentEvent


class FlowControllerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        # 模块级导入 get_engine 的使用方各自 patch；函数内导入走 app.database。
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_events = patch("app.agents.events.get_engine", return_value=self.engine)
        self.patch_events.start()
        self.patch_ledger = patch(
            "app.scheduler.run_ledger.get_engine", return_value=self.engine
        )
        self.patch_ledger.start()
        self.notify_mock = MagicMock()
        # flow_controller 模块级导入 notify，patch 使用方模块。
        self.patch_notify = patch("app.agents.flow_controller.notify", self.notify_mock)
        self.patch_notify.start()

    def tearDown(self):
        self.patch_notify.stop()
        self.patch_ledger.stop()
        self.patch_events.stop()
        self.patch_engine.stop()
        self.engine.dispose()

    def test_prepare_slot_wraps_and_records_events(self):
        payload = {
            "tz": "Asia/Shanghai",
            "hour": 10,
            "day": "2026-09-17",
            "prepared_at": "2026-09-17T09:45:00+08:00",
            "messages": {"g1": "m1"},
        }
        with patch(
            "app.agents.flow_controller.prepare_duzhan", return_value=payload
        ):
            result = flow_controller.prepare_performance_slot(
                "Asia/Shanghai", 10,
                now=datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertEqual(result["status"], "ok")
        from sqlmodel import select as _select

        with Session(self.engine) as session:
            events = session.exec(_select(AgentEvent)).all()
        types = {item.event_type for item in events}
        self.assertIn("slot.collect_started", types)
        self.assertIn("slot.collect_completed", types)
        # 同一档位重复调用被幂等拦截
        with patch(
            "app.agents.flow_controller.prepare_duzhan", return_value=payload
        ):
            second = flow_controller.prepare_performance_slot(
                "Asia/Shanghai", 10,
                now=datetime(2026, 9, 17, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertEqual(second.get("skipped"), "already_claimed")

    def test_push_slot_partial_failure_notifies(self):
        with patch(
            "app.agents.flow_controller.run_duzhan",
            return_value={"sent": ["g1"], "failed": ["g2"]},
        ):
            result = flow_controller.push_performance_slot(
                "Asia/Shanghai", 10,
                now=datetime(2026, 9, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertEqual(result["status"], "partial")
        self.assertTrue(self.notify_mock.called)

    def test_push_slot_all_sent(self):
        with patch(
            "app.agents.flow_controller.run_duzhan",
            return_value={"sent": ["g1", "g2", "g3", "g4"], "failed": []},
        ):
            result = flow_controller.push_performance_slot(
                "Asia/Shanghai", 10,
                now=datetime(2026, 9, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(self.notify_mock.called)

    def test_weekend_skips(self):
        # 2026-09-19 是周六（Asia/Shanghai）
        result = flow_controller.prepare_performance_slot(
            "Asia/Shanghai", 10,
            now=datetime(2026, 9, 19, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertEqual(result.get("skipped"), "weekend")

    def test_ctob_wrapper(self):
        with patch(
            "app.ctob.run_ctob",
            return_value={"sent": ["owner-1"], "failed": []},
        ):
            result = flow_controller.run_ctob_evening(
                now=datetime(2026, 9, 17, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sent"], ["owner-1"])

    def test_event_idempotency(self):
        self.assertTrue(write_event("task.received", event_key="k1", producer="t"))
        self.assertFalse(write_event("task.received", event_key="k1", producer="t"))
        from sqlmodel import select as _select2

        with Session(self.engine) as session:
            rows = session.exec(
                _select2(AgentEvent).where(AgentEvent.event_key == "k1")
            ).all()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
