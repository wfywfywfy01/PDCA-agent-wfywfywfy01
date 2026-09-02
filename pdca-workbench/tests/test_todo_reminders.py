# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）核心服务单测。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.models.im_replies import ImRemindSend  # noqa: F401 — 保证 create_all 建 im_remind_sends 表
from app.todos.service import (
    _match_user,
    build_person_message,
    list_pending_tasks,
    round_label_for_time,
    run_todo_reminders,
)


def _seed(session: Session, **kwargs) -> PdcaTask:
    defaults = {
        "task_date": datetime.now().strftime("%Y-%m-%d"),
        "title": "测试待办",
        "owner": "测试员",
        "status": "pending",
    }
    defaults.update(kwargs)
    row = PdcaTask(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


class TodoReminderTests(unittest.TestCase):
    """催办选人/分组/频控/失败路径。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "pdca-todo-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        # 默认 IM 组织查询与发送均为成功
        self.patch_users = patch(
            "app.todos.service.run_vertu_sync_json",
            return_value=[{"user_id": 88, "name": "测试员"}],
        )
        self.patch_send = patch(
            "app.todos.service.run_vertu_sync", return_value=(0, "", "")
        )
        self.mock_users = self.patch_users.start()
        self.patch_send.start()
        # 结果落盘不写真实 data/outbox
        self.patch_outbox = patch(
            "app.todos.service._write_outbox", lambda result: None
        )
        self.patch_outbox.start()

    def tearDown(self):
        self.patch_outbox.stop()
        self.patch_send.stop()
        self.patch_users.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_round_label_for_time(self):
        self.assertEqual(round_label_for_time("09:30"), "morning")
        self.assertEqual(round_label_for_time("16:30"), "afternoon")
        self.assertEqual(round_label_for_time("10:00"), "auto-1000")

    def test_match_user_exact_and_ambiguous(self):
        users = [
            {"user_id": 1, "name": "何海文"},
            {"user_id": 2, "name": "何海文-华东"},
        ]
        self.assertEqual(_match_user("何海文", users)["user_id"], 1)
        self.assertIsNone(_match_user("海文", users))  # 包含匹配不唯一
        self.assertIsNone(_match_user("不存在", users))

    def test_pending_selection_scope(self):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            _seed(session, task_date=today, title="今日待办")
            _seed(session, task_date=yesterday, title="逾期待办")
            _seed(session, task_date=today, title="已完成", status="done")
            _seed(session, task_date=today, title="无负责人", owner="")
            _seed(session, task_date=tomorrow, title="未到期")
        rows = list_pending_tasks(today)
        # 逾期在前（按 task_date 升序），今日在后
        self.assertEqual([r.title for r in rows], ["逾期待办", "今日待办"])

    def test_message_grouping_one_message_per_person(self):
        body = build_person_message(
            "测试员",
            [
                _make_task("逾期任务", "2026-08-16"),
                _make_task("今日任务", "2026-08-18"),
            ],
            today="2026-08-18",
            entry_url="https://example/app/",
        )
        self.assertIn("你还有 2 项待办未完成", body)
        self.assertIn("[逾期 2026-08-16] 逾期任务", body)
        self.assertIn("[今日] 今日任务", body)
        self.assertIn("https://example/app/", body)

    def test_send_success_marks_reminded(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = _seed(session, task_date=today)
            task_id = row.id
        result = run_todo_reminders(today=today, round_label="manual", force=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(result["sent"][0]["user_id"], 88)
        self.assertIn("催办 1 条消息", result["summary"])
        with Session(self.engine) as session:
            updated = session.get(PdcaTask, task_id)
            self.assertEqual(updated.last_reminded_round, "manual")
            self.assertEqual(updated.remind_count, 1)
            self.assertIsNotNone(updated.last_reminded_at)

    def test_owner_not_found_skipped(self):
        self.mock_users.return_value = []
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            _seed(session, task_date=today, owner="查无此人")
        result = run_todo_reminders(today=today, round_label="manual", force=True)
        self.assertEqual(result["sent"], [])
        self.assertEqual(result["skipped_owners"][0]["owner"], "查无此人")
        self.assertEqual(result["skipped_owners"][0]["reason"], "im_user_not_found")

    def test_frequency_control_same_round_once_per_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = _seed(session, task_date=today)
            row.last_reminded_at = datetime.now()
            row.last_reminded_round = "morning"
            row.remind_count = 1
            session.add(row)
            session.commit()
        # 同轮次同一天：跳过
        result = run_todo_reminders(today=today, round_label="morning", force=False)
        self.assertEqual(result["sent"], [])
        self.assertEqual(result["candidates"], 0)
        # 下午轮次：正常催
        result = run_todo_reminders(today=today, round_label="afternoon", force=False)
        self.assertEqual(len(result["sent"]), 1)
        # 昨天催过的：今天同轮照常催
        with Session(self.engine) as session:
            row2 = _seed(session, task_date=today, title="昨天催过的")
            row2.last_reminded_at = datetime.now() - timedelta(days=1)
            row2.last_reminded_round = "morning"
            session.add(row2)
            session.commit()
        result = run_todo_reminders(today=today, round_label="morning", force=False)
        all_titles = [
            title for s in result["sent"] for title in s["titles"]
        ]
        self.assertIn("昨天催过的", all_titles)
        self.assertIn("测试待办", all_titles)  # 下午轮催过的，上午轮仍可催（每日两轮）

    def test_manual_force_bypasses_frequency(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = _seed(session, task_date=today)
            row.last_reminded_at = datetime.now()
            row.last_reminded_round = "morning"
            session.add(row)
            session.commit()
        result = run_todo_reminders(today=today, round_label="manual", force=True)
        self.assertEqual(len(result["sent"]), 1)

    def test_dry_run_previews_without_sending(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = _seed(session, task_date=today)
            task_id = row.id
        send_mock = patch("app.todos.service.run_vertu_sync")
        mock_obj = send_mock.start()
        outbox_mock = patch("app.todos.service._write_outbox")
        mock_outbox = outbox_mock.start()
        try:
            result = run_todo_reminders(today=today, round_label="manual", force=True, dry_run=True)
            mock_obj.assert_not_called()
            mock_outbox.assert_not_called()  # dry-run 不得覆盖真实 outbox
        finally:
            outbox_mock.stop()
            send_mock.stop()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["sent"][0]["dry_run"], True)
        with Session(self.engine) as session:
            updated = session.get(PdcaTask, task_id)
            self.assertIsNone(updated.last_reminded_at)
            self.assertEqual(updated.remind_count, 0)

    def test_send_failure_reported_and_not_marked(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            row = _seed(session, task_date=today)
            task_id = row.id
        fail_mock = patch(
            "app.todos.service.run_vertu_sync", return_value=(1, "", "send error")
        )
        fail_mock.start()
        try:
            result = run_todo_reminders(today=today, round_label="manual", force=True)
        finally:
            fail_mock.stop()
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("send error", result["failed"][0]["reason"])
        with Session(self.engine) as session:
            updated = session.get(PdcaTask, task_id)
            self.assertIsNone(updated.last_reminded_at)
            self.assertEqual(updated.remind_count, 0)

    def test_project_id_grouping_preferred_over_title(self):
        # 行上挂了项目（会议项目），标题不命中任何关键词 → 仍按项目卡片推送
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            proj = TodoProject(
                key="mtg:abc", name="会议主题项目", kind="meeting",
                status="跟进中", executors="[]", coordinator="",
            )
            session.add(proj)
            session.commit()
            session.refresh(proj)
            _seed(
                session, task_date=today, title="整理门店话术手册", owner="测试员",
                status="pending", source="vemory", meeting_name="某会议",
                project_id=proj.id,
            )
        result = run_todo_reminders(today=today, round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertEqual(result["sent"][0]["project"], "会议主题项目")
        self.assertEqual(result["sent"][0]["kind"], "meeting")
        self.assertIn("【PDCA 项目待办】会议主题项目", result["sent"][0]["preview"])

    def test_unassigned_task_stays_solo_person_message(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            _seed(session, task_date=today, title="没有任何关键词的散单", owner="测试员")
        result = run_todo_reminders(today=today, round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        self.assertNotIn("project", result["sent"][0])
        self.assertIn("【PDCA 待办催办】", result["sent"][0]["preview"])

    def test_closed_meeting_project_reopened_when_tasks_return(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            proj = TodoProject(
                key="mtg:xyz", name="已闭环会议项目", kind="meeting",
                status="已闭环", executors="[]", coordinator="",
            )
            session.add(proj)
            session.commit()
            session.refresh(proj)
            _seed(
                session, task_date=today, title="又冒出来的待办", owner="测试员",
                status="pending", source="vemory", project_id=proj.id,
            )
        result = run_todo_reminders(today=today, round_label="manual", force=True, dry_run=True)
        self.assertEqual(result["sent"], [])  # dry-run 不改库、不重开 → 已闭环跳过
        result = run_todo_reminders(today=today, round_label="manual", force=True)
        self.assertEqual(len(result["sent"]), 1)  # 真实轮自动重开并推送
        self.assertEqual(result["sent"][0]["project"], "已闭环会议项目")
        with Session(self.engine) as session:
            proj = session.exec(select(TodoProject)).all()[0]
            self.assertEqual(proj.status, "跟进中")


def _make_task(title: str, task_date: str) -> PdcaTask:
    return PdcaTask(
        task_date=task_date,
        title=title,
        owner="测试员",
        status="pending",
    )


if __name__ == "__main__":
    unittest.main()
