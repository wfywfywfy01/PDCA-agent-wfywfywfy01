"""小黑屋学习任务不得进入其他群的催办、通报和自动改写。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.models.todo_group_state import TodoGroupState  # noqa: F401 - register table
from app.models.todo_project import TodoProject  # noqa: F401 - register table


class HeiwuSourceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite:///{(self.root / 'isolation.sqlite').as_posix()}")
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            todo_remind_skip_owners=[], todo_owner_aliases={},
            todo_group_channel_id="other-group", mvp_root=self.root,
        )
        with Session(self.engine) as session:
            shared = PdcaTask(task_date="2026-10-23", title="跟进客户", owner="测试甲", source="vemory")
            learning = PdcaTask(task_date="2026-10-23", title="学习作业", owner="测试甲",
                                source="heiwu_group_task", group_channel_id="learning-group")
            session.add_all([shared, learning])
            session.commit()
            session.refresh(shared)
            session.refresh(learning)
            self.shared_id, self.learning_id = shared.id, learning.id

    def _patch_module(self, name):
        self.enterContext(patch(f"{name}.get_engine", return_value=self.engine))
        self.enterContext(patch(f"{name}.get_settings", return_value=self.settings))

    def _learning(self):
        with Session(self.engine) as session:
            return session.get(PdcaTask, self.learning_id)

    def test_group_agent_only_reads_learning_tasks_in_exact_source_channel(self):
        from app.agents.group_context import load_open_tasks

        with patch("app.database.get_engine", return_value=self.engine):
            for arguments in ({}, {"owners": ("测试甲",)},
                              {"owners": ("测试甲",), "channel_id": "other-group"}):
                with self.subTest(arguments=arguments):
                    self.assertNotIn(self.learning_id, {row["id"] for row in load_open_tasks(**arguments)})
            exact = load_open_tasks(channel_id="learning-group")
        self.assertIn(self.learning_id, {row["id"] for row in exact})

    def test_manager_briefs_exclude_learning_tasks_and_escalation(self):
        from app.todos.brief import build_daily_brief, build_weekly_brief

        self._patch_module("app.todos.brief")
        with Session(self.engine) as session:
            row = session.get(PdcaTask, self.learning_id)
            row.owner, row.status = "仅学习成员", "done"
            session.add(row)
            session.commit()
        self.assertNotIn("仅学习成员", build_daily_brief("2026-10-23"))
        self.assertNotIn("仅学习成员", build_weekly_brief("2026-10-23"))
        self.assertIn("测试甲", build_daily_brief("2026-10-23"))

    def test_other_group_acknowledgement_does_not_claim_learning_tasks(self):
        from app.todos.claims import collect_group_claims

        self._patch_module("app.todos.claims")
        with patch("app.todos.claims.run_vertu_sync_json", return_value={"messages": [
            {"id": "claim", "sender_user_id": 101, "body": "收到"},
        ]}), patch("app.todos.claims._user_name", return_value="测试甲"), \
                patch("app.todos.implicit.extract_implicit_tasks", return_value={}):
            collect_group_claims("2026-10-23")
        self.assertIsNone(self._learning().claimed_at)
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(PdcaTask, self.shared_id).claimed_at)

    def test_generic_scoring_does_not_penalize_learning_tasks(self):
        from app.todos.scoring import run_scoring

        self._patch_module("app.todos.scoring")
        with patch("app.todos.scoring.fetch_department_reports", return_value={}):
            result = run_scoring("2026-10-23")
        self.assertEqual(result["scored"], 1)
        self.assertIsNone(self._learning().score)

    def test_okr_catalog_and_automatic_linking_exclude_learning_tasks(self):
        from app.todos.okr_link import fetch_okr_catalog, link_tasks_and_projects

        self._patch_module("app.todos.okr_link")
        with Session(self.engine) as session:
            row = session.get(PdcaTask, self.learning_id)
            row.owner = "仅学习成员"
            session.add(row)
            session.commit()
        with patch("app.todos.okr_link.run_vertu_sync_json", return_value={}) as cli:
            fetch_okr_catalog()
        self.assertFalse(any("仅学习成员" in call.args[0] for call in cli.call_args_list))
        candidate = {"id": "o1", "title": "示例目标"}
        with patch("app.todos.okr_link.fetch_okr_catalog", return_value=[candidate]), \
                patch("app.todos.okr_link.okr_pool_for", return_value=[candidate]), \
                patch("app.todos.okr_link.assign_okr", return_value=candidate):
            link_tasks_and_projects()
        self.assertEqual(self._learning().okr_title, "")
        with Session(self.engine) as session:
            self.assertEqual(session.get(PdcaTask, self.shared_id).okr_title, "示例目标")

    def test_csv_import_cannot_overwrite_same_title_learning_assignment(self):
        from app.models.sync import sync_pdca_tasks_from_csv

        self._patch_module("app.models.sync")
        folder = self.root / "inputs" / "todos"
        folder.mkdir(parents=True)
        (folder / "2026-10-23_todos.csv").write_text(
            "title,owner,status\n学习作业,CSV执行人,done\n", encoding="utf-8",
        )
        self.assertEqual(sync_pdca_tasks_from_csv("2026-10-23"), 1)
        learning = self._learning()
        self.assertEqual((learning.owner, learning.status), ("测试甲", "pending"))
        with Session(self.engine) as session:
            imported = session.exec(select(PdcaTask).where(PdcaTask.owner == "CSV执行人")).one()
            self.assertEqual(imported.status, "done")


if __name__ == "__main__":
    unittest.main()
