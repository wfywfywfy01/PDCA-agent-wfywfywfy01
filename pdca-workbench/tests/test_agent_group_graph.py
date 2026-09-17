# -*- coding: utf-8 -*-
"""群 Agent 状态机测试：闭环铁律、证据核验、一图多实例、任务写回。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.agents.group_graph import (
    STATUS_FLOW,
    GroupGraph,
    apply_task_updates,
    classify_task,
    is_ack_only,
    next_status,
    verify_claims,
)
from app.agents.group_context import GroupConfig, performance_group_configs
from app.models.pdca_task import PdcaTask


def _config(slot="10:00", owners=("于冰",)) -> GroupConfig:
    return GroupConfig(
        group_type="performance",
        channel_id="channel-test",
        timezone="Asia/Shanghai",
        language="zh",
        owners=owners,
        slot=slot,
        date="2026-09-17",
        group_name="测试群",
    )


class StateMachineTests(unittest.TestCase):
    def test_forward_transitions(self):
        for status, expected in STATUS_FLOW.items():
            self.assertEqual(next_status(status), expected)
        self.assertEqual(next_status("done"), "done")
        self.assertEqual(next_status("weird"), "weird")

    def test_ack_only_detection(self):
        self.assertTrue(is_ack_only("收到"))
        self.assertTrue(is_ack_only("好的"))
        self.assertTrue(is_ack_only("OK"))
        self.assertFalse(is_ack_only("收到，已联系客户并拿到水单，明天到账"))
        self.assertFalse(is_ack_only(""))

    def test_classify_task_statuses(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        self.assertEqual(classify_task({"status": "done"}, now), "done")
        self.assertEqual(classify_task({"status": "pending", "blocked_reason": "等中台"}, now), "blocked")
        overdue = (now - timedelta(days=1)).isoformat()
        self.assertEqual(
            classify_task({"status": "in_progress", "due_at": overdue}, now), "overdue"
        )
        self.assertEqual(
            classify_task({"status": "claimed", "due_at": (now + timedelta(days=1)).isoformat()}, now),
            "claimed",
        )
        self.assertEqual(classify_task({"status": "pending"}, now), "pending")

    def test_verify_claims_rules(self):
        # 只有“收到”回复、无证据 -> 不闭环
        status, missing = verify_claims({"verification_status": "unverified", "reply_text": "收到", "evidence": []})
        self.assertEqual(status, "unverified")
        self.assertTrue(missing)
        # 证据类型不在白名单 -> 不推进
        status, _ = verify_claims({"verification_status": "unverified", "evidence": [{"evidence_type": "gossip"}]})
        self.assertEqual(status, "unverified")
        # 有效证据 -> partial
        status, _ = verify_claims({"verification_status": "unverified", "evidence": [{"evidence_type": "im_message"}]})
        self.assertEqual(status, "partial")
        # 人工确认 -> verified
        status, _ = verify_claims({"verification_status": "unverified", "evidence": [{"evidence_type": "manual_confirmation"}]})
        self.assertEqual(status, "verified")
        # 已 verified 保持不变
        status, _ = verify_claims({"verification_status": "verified", "evidence": []})
        self.assertEqual(status, "verified")



class GroupGraphPipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_events = patch("app.agents.events.get_engine", return_value=self.engine)
        self.patch_events.start()

    def tearDown(self):
        self.patch_events.stop()
        self.patch_engine.stop()
        self.engine.dispose()

    def test_run_produces_valid_output(self):
        graph = GroupGraph(_config())
        state = graph.run(snapshot=None, prev_snapshot=None)
        output = state["output"]
        self.assertEqual(output.group_channel_id, "channel-test")
        self.assertEqual(output.slot, "10:00")
        # 影子模式确定性草稿不是空
        self.assertTrue(state["draft_message"])
        self.assertIn(output.approval_policy, ("auto_template", "manual_required"))

    def test_one_graph_many_instances(self):
        """一套图多实例：五个达标群 + Lina 巴黎，各自独立配置。"""
        configs = performance_group_configs("2026-09-17")
        self.assertEqual(len(configs), 5)
        channels = {item.channel_id for item in configs}
        self.assertEqual(len(channels), 5, "群 channel 不得串群")
        lina = [item for item in configs if item.group_name == "Lina业绩达标群"][0]
        self.assertEqual(lina.timezone, "Europe/Paris")
        self.assertEqual(lina.language, "en")
        shanghai = [item for item in configs if item.group_name == "于冰业绩达标群"][0]
        self.assertEqual(shanghai.timezone, "Asia/Shanghai")
        self.assertEqual(shanghai.language, "zh")

    def test_apply_task_updates_respects_owner_locked(self):
        with Session(self.engine) as session:
            task = PdcaTask(
                task_date="2026-09-17", title="确认越南 PO 尾款", owner="于冰",
                status="in_progress", owner_locked=True,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id
        result = apply_task_updates(updates=[
            {"task_id": task_id, "owner": "何海文", "to_status": "done"},
        ])
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(result["skipped"]), 1)
        with Session(self.engine) as session:
            stored = session.get(PdcaTask, task_id)
        self.assertEqual(stored.status, "in_progress")

    def test_apply_task_updates_closes_verified(self):
        with Session(self.engine) as session:
            task = PdcaTask(
                task_date="2026-09-17", title="回款跟进", owner="于冰",
                status="evidence_submitted",
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id
        result = apply_task_updates(updates=[
            {"task_id": task_id, "to_status": "done", "verification_status": "verified"},
        ])
        self.assertEqual(result["updated"], 1)
        with Session(self.engine) as session:
            stored = session.get(PdcaTask, task_id)
        self.assertEqual(stored.status, "done")
        self.assertEqual(stored.verification_status, "verified")
        self.assertIsNotNone(stored.closed_at)


if __name__ == "__main__":
    unittest.main()

