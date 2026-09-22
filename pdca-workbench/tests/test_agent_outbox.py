# -*- coding: utf-8 -*-
"""Outbox 测试：幂等、强制人工审批、状态机、发送轮与重试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.models import AgentOutbox
from app.agents import outbox as outbox_module


class _FakeSettings:
    """仅覆盖本测试需要的设置项。"""

    def __init__(self, auto_push: bool = False, outbox_enabled: bool = True):
        self.agent_auto_template_push = auto_push
        self.agent_outbox_enabled = outbox_enabled


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        # outbox.py 在模块级导入 get_engine，必须 patch 使用方模块。
        self.patch_engine = patch("app.agents.outbox.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_log = patch("app.agents.outbox.log_action", MagicMock())
        self.patch_log.start()
        self.notify_mock = MagicMock()
        self.patch_notify = patch("app.alerting.notify", self.notify_mock)
        self.patch_notify.start()
        self.settings = _FakeSettings()
        self.patch_settings = patch(
            "app.agents.outbox.get_settings", return_value=self.settings
        )
        self.patch_settings.start()

    def tearDown(self):
        self.patch_settings.stop()
        self.patch_notify.stop()
        self.patch_log.stop()
        self.patch_engine.stop()
        self.engine.dispose()

    def test_same_idempotency_key_only_one_row(self):
        first = outbox_module.create_outbox(
            idempotency_key="dup-key",
            channel_id="channel-1",
            body="催办草稿",
            approval_policy="manual_required",
        )
        second = outbox_module.create_outbox(
            idempotency_key="dup-key",
            channel_id="channel-1",
            body="另一条",
            approval_policy="manual_required",
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        with Session(self.engine) as session:
            rows = session.exec(select(AgentOutbox)).all()
        self.assertEqual(len(rows), 1)

    def test_risky_body_forced_manual(self):
        row = outbox_module.create_outbox(
            idempotency_key="penalty-1",
            channel_id="channel-1",
            body="拟对某人执行扣罚 100 元",
            message_kind="penalty",
            approval_policy="auto_template",
        )
        self.assertEqual(row.approval_policy, "manual_required")
        self.assertEqual(row.approval_status, "pending")

    def test_auto_template_only_sends_when_switch_on(self):
        self.settings.agent_auto_template_push = False
        row = outbox_module.create_outbox(
            idempotency_key="auto-off",
            channel_id="channel-1",
            body="常规催办",
            approval_policy="auto_template",
        )
        self.assertEqual(row.approval_status, "pending")
        self.settings.agent_auto_template_push = True
        row2 = outbox_module.create_outbox(
            idempotency_key="auto-on",
            channel_id="channel-1",
            body="常规催办",
            approval_policy="auto_template",
        )
        self.assertEqual(row2.approval_status, "approved")
        self.assertEqual(row2.approved_by, "auto")

    def test_approve_reject_state_machine(self):
        row = outbox_module.create_outbox(
            idempotency_key="flow-1",
            channel_id="channel-1",
            body="待审批草稿",
            approval_policy="manual_required",
        )
        result = outbox_module.approve_outbox(row.id, "admin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["approval_status"], "approved")
        again = outbox_module.approve_outbox(row.id, "admin")
        self.assertFalse(again["ok"])
        row2 = outbox_module.create_outbox(
            idempotency_key="flow-2",
            channel_id="channel-1",
            body="另一条",
        )
        result = outbox_module.reject_outbox(row2.id, "admin", "不需要发")
        self.assertTrue(result["ok"])
        with Session(self.engine) as session:
            stored = session.get(AgentOutbox, row2.id)
        self.assertEqual(stored.approval_status, "rejected")
        self.assertEqual(stored.last_error, "不需要发")

    def test_send_due_delivers_and_retries_once(self):
        self.settings.agent_auto_template_push = True
        row = outbox_module.create_outbox(
            idempotency_key="send-1",
            channel_id="channel-1",
            body="常规催办",
            approval_policy="auto_template",
        )
        push_mock = MagicMock(side_effect=[False, True])
        with patch("app.agents.outbox._deliver", push_mock):
            result = outbox_module.send_due()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(push_mock.call_count, 2)
        with Session(self.engine) as session:
            stored = session.get(AgentOutbox, row.id)
        self.assertEqual(stored.send_status, "sent")
        self.assertEqual(stored.send_attempts, 2)


    def test_failed_twice_marks_failed_and_notifies(self):
        self.settings.agent_auto_template_push = True
        row = outbox_module.create_outbox(
            idempotency_key="fail-1",
            channel_id="channel-1",
            body="常规催办",
            approval_policy="auto_template",
        )
        with patch("app.agents.outbox._deliver", MagicMock(return_value=False)):
            result = outbox_module.send_due()
        self.assertEqual(result["failed"], 1)
        with Session(self.engine) as session:
            stored = session.get(AgentOutbox, row.id)
        self.assertEqual(stored.send_status, "failed")
        self.assertEqual(stored.send_attempts, 2)
        self.assertTrue(self.notify_mock.called)

    def test_exhausted_failures_do_not_block_new_pending_rows(self):
        with Session(self.engine) as session:
            for index in range(40):
                session.add(AgentOutbox(
                    idempotency_key=f"old-failed-{index}",
                    channel_id="channel-1",
                    body="旧失败消息",
                    approval_status="approved",
                    send_status="failed",
                    send_attempts=2,
                ))
            exhausted_pending = AgentOutbox(
                idempotency_key="old-pending-exhausted",
                channel_id="channel-1",
                body="旧异常消息",
                approval_status="approved",
                send_status="pending",
                send_attempts=2,
            )
            session.add(exhausted_pending)
            fresh = AgentOutbox(
                idempotency_key="fresh-pending",
                channel_id="channel-1",
                body="新消息",
                approval_status="approved",
                send_status="pending",
            )
            session.add(fresh)
            session.commit()
            session.refresh(exhausted_pending)
            session.refresh(fresh)
            exhausted_pending_id = exhausted_pending.id
            fresh_id = fresh.id
        deliver = MagicMock(return_value=True)
        with patch("app.agents.outbox._deliver", deliver):
            result = outbox_module.send_due(limit=40)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(deliver.call_count, 1)
        with Session(self.engine) as session:
            exhausted = session.get(AgentOutbox, exhausted_pending_id)
            self.assertEqual(exhausted.send_status, "pending")
            self.assertEqual(exhausted.send_attempts, 2)
            self.assertEqual(session.get(AgentOutbox, fresh_id).send_status, "sent")

    def test_retry_reopens_failed(self):
        self.settings.agent_auto_template_push = True
        row = outbox_module.create_outbox(
            idempotency_key="retry-1",
            channel_id="channel-1",
            body="常规催办",
            approval_policy="manual_required",
        )
        with Session(self.engine) as session:
            stored = session.get(AgentOutbox, row.id)
            stored.send_status = "failed"
            stored.send_attempts = 2
            session.add(stored)
            session.commit()
        result = outbox_module.retry_outbox(row.id, "admin")
        self.assertTrue(result["ok"])
        with Session(self.engine) as session:
            stored = session.get(AgentOutbox, row.id)
        self.assertEqual(stored.send_status, "pending")
        self.assertEqual(stored.approval_status, "pending")
        self.assertEqual(stored.send_attempts, 0)

    def test_send_due_disabled_skips(self):
        self.settings.agent_outbox_enabled = False
        result = outbox_module.send_due()
        self.assertEqual(result.get("sent"), 0)
        self.assertEqual(result.get("skipped"), "outbox 发送未启用")


if __name__ == "__main__":
    unittest.main()

