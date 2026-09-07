# -*- coding: utf-8 -*-
"""日报证据匹配与催办集成单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

import app.todos.evidence as evidence_mod
from app.models.pdca_task import PdcaTask
from app.todos.evidence import (
    evidence_tokens,
    fetch_department_reports,
    has_followup,
    load_vps_user_map,
    report_text_for,
)
from app.todos.service import run_todo_reminders


class EvidenceTokenTests(unittest.TestCase):
    """与 todo-tracker.mjs selfTest 等价的三条断言。"""

    def test_self_test_parity(self):
        tokens = evidence_tokens("继续跟进迈凯伦报价")
        self.assertIn("迈凯", tokens)
        self.assertNotIn("继续", tokens)
        self.assertNotIn("跟进", tokens)

    def test_has_followup_true(self):
        self.assertTrue(
            has_followup("推进迈凯伦配件报价", "今日已推进迈凯伦项目，等待报价")
        )

    def test_has_followup_false(self):
        self.assertFalse(
            has_followup("催九六二零机器款项", "今日处理门店日常沟通")
        )


class EvidenceReminderIntegrationTests(unittest.TestCase):
    """催办引擎的日报证据抑制。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "evidence-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        # IM 用户解析成功 + 发送成功
        self.patch_users = patch(
            "app.todos.service.run_vertu_sync_json",
            return_value=[{"user_id": 88, "name": "何海文"}],
        )
        self.patch_users.start()
        self.patch_send = patch(
            "app.todos.service.run_vertu_sync", return_value=(0, "", "")
        )
        self.mock_send = self.patch_send.start()
        self.patch_outbox = patch("app.todos.service._write_outbox", lambda result: None)
        self.patch_outbox.start()
        evidence_mod._CORPUS_CACHE.clear()

    def tearDown(self):
        self.patch_outbox.stop()
        self.patch_send.stop()
        self.patch_users.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _daily_json(name="何海文", content="", user_id=14113):
        return json.dumps(
            {
                "ok": True,
                "query_scope": "all",
                "count": 1,
                "submissions": [
                    {
                        "user_id": user_id,
                        "employee_name": name,
                        "payload": {
                            "today": [
                                {"title": "例会", "content": content}
                            ]
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )

    def _seed_vemory(self, title, meeting_days_ago=3, owner="何海文"):
        today = datetime.now().strftime("%Y-%m-%d")
        meeting = (datetime.now() - timedelta(days=meeting_days_ago)).strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = PdcaTask(
                task_date=meeting,
                title=title,
                owner=owner,
                status="pending",
                source="vemory",
                meeting_date=meeting,
                meeting_name="周会",
            )
            session.add(row)
            session.commit()

    def _seed_plain(self, title, owner="何海文"):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = PdcaTask(
                task_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                title=title,
                owner=owner,
                status="pending",
                source="workbench",
            )
            session.add(row)
            session.commit()

    def test_vemory_with_evidence_not_sent(self):
        self._seed_vemory("催九六二零机器款项")  # 不命中项目词，走个人催办路径
        with patch(
            "app.todos.evidence.run_vertu_sync",
            return_value=(
                0,
                self._daily_json(content="今日已处理九六二零款项，等待回款"),
                "",
            ),
        ):
            result = run_todo_reminders(round_label="manual", force=True)
        self.assertEqual(result["sent"], [])
        self.assertEqual(len(result["evidence_skipped"]), 1)
        self.assertEqual(result["evidence_skipped"][0]["title"], "催九六二零机器款项")
        self.mock_send.assert_not_called()

    def test_vemory_without_evidence_sent(self):
        self._seed_vemory("催九六二零机器款项")
        with patch(
            "app.todos.evidence.run_vertu_sync",
            return_value=(
                0,
                self._daily_json(content="今日处理门店日常沟通"),
                "",
            ),
        ):
            result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(result["sent"][0]["titles"], ["催九六二零机器款项"])
        self.assertIn("已比对日报", result["sent"][0].get("preview", ""))

    def test_vemory_report_unavailable_still_sent_with_marker(self):
        # 日报不可用：fail-open，照常催并标注 evidence_unavailable
        self._seed_vemory("催九六二零机器款项")
        with patch(
            "app.todos.evidence.run_vertu_sync", return_value=(1, "", "timeout")
        ):
            result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(len(result["evidence_unavailable"]), 1)
        self.assertIn("日报系统暂不可用", result["sent"][0].get("preview", ""))

    def test_vemory_unmapped_owner_still_sent(self):
        # 日报聚合结果里没有该负责人 → 取不到证据，照常催 + 标注
        self._seed_vemory("催九六二零机器款项")
        with patch(
            "app.todos.evidence.run_vertu_sync",
            return_value=(0, self._daily_json(name="杨晶晶", content="无关"), ""),
        ):
            result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(len(result["evidence_unavailable"]), 1)

    def test_non_vemory_unaffected_by_evidence(self):
        self._seed_plain("工作台手工待办")
        with patch(
            "app.todos.evidence.run_vertu_sync",
            return_value=(0, self._daily_json(content="完全无关的日报"), ""),
        ):
            result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(result["sent"][0]["titles"], ["工作台手工待办"])
        self.assertIn("系统自动提醒", result["sent"][0].get("preview", ""))

    def test_report_fetch_once_per_run(self):
        self._seed_vemory("事项A")
        self._seed_vemory("事项B")
        calls = []

        def fake_report(args, timeout):
            calls.append(list(args))
            return (0, self._daily_json(content="今日处理门店日常沟通"), "")

        with patch("app.todos.evidence.run_vertu_sync", side_effect=fake_report):
            run_todo_reminders(round_label="manual", force=True)
        # 窗口 7 天各拉一次，与任务条数无关（不再按人逐个拉取）
        self.assertEqual(len(calls), 7)


class ChannelsFallbackTests(unittest.TestCase):
    """im +users 空结果时，从 +channels 反查 user_id。"""

    def setUp(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None
        service_mod._CHANNELS_SCAN = {"ts": 0.0, "map": {}}
        # +users 空；+channels 含双方会话
        def fake_json(args, timeout):
            if "+users" in args:
                return {"ok": True, "count": 0, "users": []}
            if "+channels" in args:
                return {
                    "channels": [
                        {
                            "direct_key": "u:14113:13365",
                            "name": "付汪阳, 何海文",
                        },
                        {
                            "direct_key": "u:13050:13365",
                            "name": "付汪阳, DEHDAHOUMAIMA",
                        },
                        {
                            # 自己在左侧的形态：不得把王宇彤映射成自己
                            "direct_key": "u:13365:14344",
                            "name": "付汪阳, 王宇彤",
                        },
                    ]
                }
            if "+me" in args:
                return {"ok": True, "user": {"userId": 13365}}
            return None

        self.patch_json = patch(
            "app.todos.service.run_vertu_sync_json", side_effect=fake_json
        )
        self.patch_json.start()

    def tearDown(self):
        self.patch_json.stop()

    def test_fallback_resolves_from_channels(self):
        from app.todos.service import resolve_im_user

        user = resolve_im_user("何海文", {})
        self.assertIsNotNone(user)
        self.assertEqual(user["user_id"], 14113)
        user2 = resolve_im_user("DEHDAHOUMAIMA", {})
        self.assertEqual(user2["user_id"], 13050)
        user3 = resolve_im_user("王宇彤", {})
        self.assertEqual(user3["user_id"], 14344)  # 不是 13365（自己）


class SelfSkipTests(unittest.TestCase):
    """催办引擎跳过「本人」与显式排除名单。"""

    def setUp(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None  # 每例重置单例缓存
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "selfskip-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_send = patch(
            "app.todos.service.run_vertu_sync", return_value=(0, "", "")
        )
        self.mock_send = self.patch_send.start()
        # 日报证据接口默认离线（不访问真实网络）
        self.patch_evidence = patch(
            "app.todos.evidence.run_vertu_sync", return_value=(1, "", "offline")
        )
        self.patch_evidence.start()
        self.patch_outbox = patch("app.todos.service._write_outbox", lambda result: None)
        self.patch_outbox.start()

    def tearDown(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None  # 防止单例缓存泄漏到其他测试类
        self.patch_outbox.stop()
        self.patch_evidence.stop()
        self.patch_send.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, owner="何海文"):
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                title="待办A",
                owner=owner,
                status="pending",
                source="workbench",
            ))
            session.commit()

    def test_skip_self(self):
        def fake_json(args, timeout):
            if "+me" in args:
                return {"ok": True, "user": {"userId": 88}}
            return [{"user_id": 88, "name": "何海文"}]

        self._seed()
        with patch("app.todos.service.run_vertu_sync_json", side_effect=fake_json):
            result = run_todo_reminders(round_label="manual", force=True)
        self.assertEqual(result["sent"], [])
        self.assertEqual(result["skipped_owners"][0]["reason"], "im_self")
        self.mock_send.assert_not_called()

    def test_skip_explicit_exclusion(self):
        from unittest.mock import MagicMock

        fake_settings = MagicMock()
        fake_settings.workbench_base_url = "https://example/app/"
        fake_settings.todo_remind_grace_hours = 48
        fake_settings.todo_remind_skip_owners = ["何海文"]
        self._seed()
        with patch("app.todos.service.get_settings", return_value=fake_settings):
            result = run_todo_reminders(round_label="manual", force=True)
        self.assertEqual(result["sent"], [])
        self.assertEqual(result["skipped_owners"][0]["reason"], "owner_excluded")
        self.mock_send.assert_not_called()


class ReportFetchTests(unittest.TestCase):
    """部门日报聚合拉取与姓名查文本。"""

    def setUp(self):
        evidence_mod._CORPUS_CACHE.clear()

    @staticmethod
    def _payload(name="何海文", content="日报正文"):
        return json.dumps(
            {
                "ok": True,
                "query_scope": "all",
                "submissions": [
                    {
                        "user_id": 14113,
                        "employee_name": name,
                        "payload": {"today": [{"title": "例会", "content": content}]},
                    }
                ],
            },
            ensure_ascii=False,
        )

    def test_fetch_department_reports_and_lookup(self):
        with patch(
            "app.todos.evidence.run_vertu_sync",
            return_value=(0, self._payload(content="日报正文"), ""),
        ):
            corpus = fetch_department_reports(["2026-09-07"])
        self.assertEqual(report_text_for("何海文", corpus), "例会\n日报正文")
        self.assertIsNone(report_text_for("不存在的人", corpus))

    def test_fetch_failure_returns_empty(self):
        with patch("app.todos.evidence.run_vertu_sync", return_value=(1, "", "err")):
            corpus = fetch_department_reports(["2026-09-08"])
        self.assertEqual(corpus, {})

    def test_unique_containment_lookup(self):
        corpus = {"冯磊-1": {"user_id": 12545, "texts": ["abc"]}}
        self.assertEqual(report_text_for("冯磊", corpus), "abc")
        # 包含匹配不唯一时不猜
        ambiguous = {
            "张三分": {"user_id": 1, "texts": ["a"]},
            "张三丰": {"user_id": 2, "texts": ["b"]},
        }
        self.assertIsNone(report_text_for("张三", ambiguous))

    def test_vps_user_map(self):
        with patch(
            "app.todos.evidence.load_vemory_users",
            return_value=[
                {"name": "何海文", "vmemoryUserId": 109, "vpsUserId": 14113},
                {"name": "无ID人", "vmemoryUserId": 1},
            ],
        ):
            mapping = load_vps_user_map()
        self.assertEqual(mapping, {"何海文": 14113})


if __name__ == "__main__":
    unittest.main()
