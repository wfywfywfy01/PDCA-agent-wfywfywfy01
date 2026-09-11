# -*- coding: utf-8 -*-
"""群聊隐式任务抽取与进度追加单测。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.todos.implicit import extract_implicit_tasks
from app.todos.replies import _append_progress as append_progress


class ImplicitExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "implicit-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.implicit.get_engine", return_value=self.engine
        )
        self.patch_engine.start()

    def tearDown(self):
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _tasks(self):
        with Session(self.engine) as session:
            return list(session.exec(select(PdcaTask)).all())

    def _msg(self, sender, body):
        return {"sender_user_id": sender, "body": body, "id": str(abs(hash(body)))}

    def test_assign_pattern_creates_task_with_deadline(self):
        extract_implicit_tasks([
            self._msg(13365, "让何海文整理印度客户名单，明天发我")
        ])
        tasks = self._tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].owner, "何海文")
        self.assertEqual(tasks[0].source, "group-implicit")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(tasks[0].task_date, tomorrow)

    def test_at_mention_creates_task(self):
        extract_implicit_tasks([
            self._msg(13365, "@于冰 整理马来对接资料")
        ])
        tasks = self._tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].owner, "于冰")

    def test_alias_normalized(self):
        extract_implicit_tasks([
            self._msg(13365, "让Lina完成迪拜客户盘点")
        ])
        tasks = self._tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].owner, "DEHDAHOUMAIMA")

    def test_non_manager_skipped(self):
        extract_implicit_tasks([
            self._msg(99999, "让何海文整理印度客户名单")
        ])
        self.assertEqual(len(self._tasks()), 0)

    def test_unknown_owner_skipped(self):
        extract_implicit_tasks([
            self._msg(13365, "让路人甲完成莫名其妙的事")
        ])
        self.assertEqual(len(self._tasks()), 0)

    def test_idempotent_same_message(self):
        msg = self._msg(13365, "让何海文整理印度客户名单")
        extract_implicit_tasks([msg])
        extract_implicit_tasks([msg])
        self.assertEqual(len(self._tasks()), 1)


class AppendProgressTests(unittest.TestCase):
    def test_append_accumulates_and_caps(self):
        now = datetime(2026, 9, 11, 10, 0)
        text = append_progress("", "第1条完成", now)
        self.assertEqual(text, "09-11：第1条完成")
        text = append_progress(text, "第2条推进中", now)
        self.assertIn("第1条完成", text)
        self.assertIn("第2条推进中", text)
        for i in range(3, 9):
            text = append_progress(text, f"第{i}条有进展", now)
        self.assertEqual(len(text.splitlines()), 5)
        self.assertNotIn("第1条完成", text)  # 超出 5 条被裁掉
        self.assertIn("第8条有进展", text)


if __name__ == "__main__":
    unittest.main()
