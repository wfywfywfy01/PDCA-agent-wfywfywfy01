# -*- coding: utf-8 -*-
"""IM 回复解析与采集单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.im_replies import ImRemindSend, TodoReply
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.todos.replies import parse_reply, poll_replies


class ParseReplyTests(unittest.TestCase):
    def test_done_with_item_number(self):
        r = parse_reply("第2条已完成")
        self.assertEqual(r["signal"], "done")
        self.assertEqual(r["items"], [2])
        self.assertTrue(r["explicit"])

    def test_done_multiple_numbers(self):
        r = parse_reply("1和3完成了，请更新")
        self.assertEqual(r["signal"], "done")
        self.assertEqual(r["items"], [1, 3])

    def test_done_all(self):
        r = parse_reply("全部都完成了")
        self.assertEqual(r["signal"], "done")
        self.assertEqual(r["items"], ["all"])
        self.assertTrue(r["explicit"])

    def test_done_vague(self):
        r = parse_reply("有一条已经完成")
        self.assertEqual(r["signal"], "done")
        self.assertFalse(r["explicit"])

    def test_progress(self):
        self.assertEqual(parse_reply("在推进了")["signal"], "progress")

    def test_blocker(self):
        self.assertEqual(parse_reply("卡住了，需要支持")["signal"], "blocker")

    def test_no_signal(self):
        self.assertEqual(parse_reply("收到")["signal"], "")


class PollRepliesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "replies-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.replies.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_users = patch(
            "app.todos.service.run_vertu_sync_json",
            return_value=[{"user_id": 14113, "name": "何海文"}],
        )
        self.patch_users.start()
        self.patch_json = patch(
            "app.todos.replies.run_vertu_sync_json",
            side_effect=self._fake_im_json,
        )
        self.patch_json.start()
        self.patch_notify = patch("app.todos.replies._notify_coordinator")
        self.mock_notify = self.patch_notify.start()

    def tearDown(self):
        self.patch_notify.stop()
        self.patch_json.stop()
        self.patch_users.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _fake_im_json(self, args, timeout):
        if "+chat" in args:
            return {"channel": {"id": "ch-1"}}
        if "+history" in args:
            return {"channel_id": "ch-1", "messages": self.history_messages}
        return None

    def _seed(self, replies_text):
        now = datetime.now()
        with Session(self.engine) as session:
            project = TodoProject(key="india-distro", name="印度总代/独代谈判", executors='["何海文"]', coordinator="刘春梅")
            session.add(project)
            session.commit()
            session.refresh(project)
            t1 = PdcaTask(task_date="2026-08-20", title="印度总代任务A", owner="何海文", status="pending", source="vemory", project_id=project.id)
            t2 = PdcaTask(task_date="2026-08-20", title="印度总代任务B", owner="何海文", status="pending", source="vemory", project_id=project.id)
            session.add(t1)
            session.add(t2)
            session.commit()
            session.refresh(t1)
            session.refresh(t2)
            send = ImRemindSend(
                person="何海文",
                sent_at=now - timedelta(hours=1),
                message_id="msg-1",
                item_task_ids=json.dumps([t1.id, t2.id]),
                project_id=project.id,
                round="manual",
            )
            session.add(send)
            session.commit()
            result = (int(t1.id), int(t2.id), int(project.id), int(send.id))
        self.history_messages = [
            {
                "id": "r1",
                "sender_user_id": 14113,
                "body": replies_text,
                "parent_message_id": "msg-1",
                "created_at": (now - timedelta(minutes=10)).isoformat(),
            }
        ]
        return result

    def test_done_explicit_applies(self):
        t1, t2, project, send = self._seed("第1条已完成")
        result = poll_replies()
        self.assertEqual(result["applied"], 1)
        with Session(self.engine) as session:
            task = session.get(PdcaTask, t1)
            self.assertEqual(task.status, "done")
            task2 = session.get(PdcaTask, t2)
            self.assertEqual(task2.status, "pending")

    def test_done_all_project_to_verify(self):
        t1, t2, project, send = self._seed("全部完成了")
        result = poll_replies()
        self.assertEqual(result["applied"], 1)
        with Session(self.engine) as session:
            p = session.get(TodoProject, project)
            self.assertEqual(p.status, "待验收")

    def test_vague_done_queued(self):
        t1, t2, project, send = self._seed("有一条已经完成")
        result = poll_replies()
        self.assertEqual(result["queued"], 1)
        with Session(self.engine) as session:
            task = session.get(PdcaTask, t1)
            self.assertEqual(task.status, "pending")
            reply = session.exec(select(TodoReply)).all()[0]
            self.assertEqual(reply.status, "unreviewed")

    def test_blocker_sets_status(self):
        t1, t2, project, send = self._seed("卡住了，需要支持")
        result = poll_replies()
        with Session(self.engine) as session:
            p = session.get(TodoProject, project)
            self.assertEqual(p.status, "阻塞")
        self.mock_notify.assert_called_once()

    def test_progress_sets_status(self):
        t1, t2, project, send = self._seed("在推进了")
        poll_replies()
        with Session(self.engine) as session:
            p = session.get(TodoProject, project)
            self.assertEqual(p.status, "跟进中")


if __name__ == "__main__":
    unittest.main()
