# -*- coding: utf-8 -*-
"""pdca_tasks 写入路径单测（F3：insert_pdca_task）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.models import writes as db_writes


class PdcaTaskWriteTests(unittest.TestCase):
    """验证 insert_pdca_task 的创建与同日同名更新语义。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "pdca-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.models.writes.get_engine", return_value=self.engine
        )
        self.patch_engine.start()

    def tearDown(self):
        self.engine.dispose()
        self.patch_engine.stop()
        self.temp_dir.cleanup()

    def _rows(self, task_date: str) -> list[PdcaTask]:
        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(PdcaTask).where(PdcaTask.task_date == task_date)
                ).all()
            )

    def test_insert_creates_row(self):
        db_writes.insert_pdca_task(
            task_date="2026-08-18",
            title="跟进 A 类客户张三",
            owner="yang-jingjing",
            status="pending",
            priority="high",
            source="workbench",
        )
        rows = self._rows("2026-08-18")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.title, "跟进 A 类客户张三")
        self.assertEqual(row.owner, "yang-jingjing")
        self.assertEqual(row.priority, "high")
        self.assertEqual(row.source, "workbench")

    def test_insert_same_day_title_updates_instead_of_duplicate(self):
        db_writes.insert_pdca_task(
            task_date="2026-08-18",
            title="回访客户李四",
            owner="he-haiwen",
            status="pending",
        )
        db_writes.insert_pdca_task(
            task_date="2026-08-18",
            title="回访客户李四",
            owner="he-haiwen",
            status="done",
        )
        rows = self._rows("2026-08-18")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "done")

    def test_blank_title_is_noop(self):
        db_writes.insert_pdca_task(task_date="2026-08-18", title="   ")
        self.assertEqual(self._rows("2026-08-18"), [])

    def test_update_by_id_updates_status_and_owner(self):
        db_writes.insert_pdca_task(
            task_date="2026-08-18",
            title="任务A",
            owner="he-haiwen",
            status="pending",
        )
        row = self._rows("2026-08-18")[0]
        ok = db_writes.update_pdca_task_by_id(
            row.id, status="done", owner="wang-yutong", priority="high"
        )
        self.assertTrue(ok)
        updated = self._rows("2026-08-18")[0]
        self.assertEqual(updated.status, "done")
        self.assertEqual(updated.owner, "wang-yutong")
        self.assertEqual(updated.priority, "high")

    def test_update_by_id_missing_returns_false(self):
        self.assertFalse(db_writes.update_pdca_task_by_id(99999, status="done"))


if __name__ == "__main__":
    unittest.main()
