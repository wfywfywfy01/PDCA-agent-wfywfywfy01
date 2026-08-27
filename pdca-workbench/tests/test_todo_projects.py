# -*- coding: utf-8 -*-
"""项目（事项）收敛与项目级催办单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.todos.projects import PROJECT_RULES, ensure_projects, match_project
from app.todos.service import run_todo_reminders


class ProjectRuleTests(unittest.TestCase):
    def test_match_basics(self):
        self.assertEqual(match_project("印度总代谈判方案")["key"], "india-distro")
        self.assertEqual(match_project("准备出货证书 UN38.3")["key"], "logistics-fulfillment")
        self.assertEqual(match_project("BIS 认证对接")["key"], "india-distro")  # 认证≠物流
        self.assertEqual(match_project("港澳退换货安排")["key"], "hk-mo-returns")
        self.assertIsNone(match_project("催九六二零机器款项"))
        self.assertEqual(match_project("Landmark NDA 签署")["key"], "landmark")

    def test_ensure_projects_seeds_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'p.sqlite'}")
            SQLModel.metadata.create_all(engine)
            try:
                with Session(engine) as session:
                    by_key, by_id = ensure_projects(session)
                    self.assertEqual(len(by_key), len(PROJECT_RULES))
                    row = by_key["india-distro"]
                    self.assertEqual(json.loads(row.executors), ["何海文", "杨晶晶"])
                    # 再跑一遍幂等
                    by_key2, _ = ensure_projects(session)
                    self.assertEqual(len(by_key2), len(PROJECT_RULES))
            finally:
                engine.dispose()


class ProjectReminderTests(unittest.TestCase):
    def setUp(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "proj-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_outbox = patch("app.todos.service._write_outbox", lambda result: None)
        self.patch_outbox.start()
        self.patch_vps_map = patch(
            "app.todos.evidence.load_vemory_users", return_value=[]
        )
        self.patch_vps_map.start()
        # IM：按查询名返回对应用户
        def fake_users(args, timeout):
            if "+me" in args:
                return {"ok": True, "user": {"userId": 999}}
            query = args[args.index("--query") + 1]
            return [{"user_id": 100 + hash(query) % 800, "name": query}]

        self.patch_json = patch(
            "app.todos.service.run_vertu_sync_json", side_effect=fake_users
        )
        self.patch_json.start()
        self.patch_send = patch(
            "app.todos.service.run_vertu_sync", return_value=(0, "", "")
        )
        self.mock_send = self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        self.patch_json.stop()
        self.patch_vps_map.stop()
        self.patch_outbox.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed_vemory(self, title, owner="何海文"):
        today = datetime.now().strftime("%Y-%m-%d")
        aged = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date=aged, title=title, owner=owner, status="pending",
                source="vemory", meeting_date=aged, meeting_name="周会",
            ))
            session.commit()

    def test_project_round_one_message_per_executor(self):
        self._seed_vemory("印度独代谈判：整理总代框架", owner="何海文")
        self._seed_vemory("印度总代保证金条款确认", owner="杨晶晶")
        result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 1)
        entry = result["sent"][0]
        self.assertEqual(entry["project"], "印度总代/独代谈判")
        self.assertEqual(sorted(entry["executors"]), ["何海文", "杨晶晶"])
        self.assertEqual(entry["tasks"], 2)
        self.assertIn("印度总代", entry["preview"])

    def test_project_closed_not_reminded(self):
        self._seed_vemory("印度独代谈判：整理总代框架")
        with Session(self.engine) as session:
            by_key, _ = ensure_projects(session)
            row = by_key["india-distro"]
            row.status = "已闭环"
            session.add(row)
            session.commit()
        result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(result["sent"], [])

    def test_project_dedup_same_round(self):
        self._seed_vemory("印度独代谈判：整理总代框架")
        first = run_todo_reminders(round_label="afternoon", force=False)
        self.assertEqual(len(first["sent"]), 1)
        second = run_todo_reminders(round_label="afternoon", force=False, dry_run=True)
        self.assertEqual(second["sent"], [])  # 同一轮同日不再催

    def test_project_mark_rows_and_project(self):
        self._seed_vemory("印度独代谈判：整理总代框架")
        run_todo_reminders(round_label="manual", force=True)
        with Session(self.engine) as session:
            task = session.exec(select(PdcaTask)).all()[0]
            self.assertEqual(task.last_reminded_round, "manual")
            project = session.exec(select(TodoProject)).all()[0]
            self.assertEqual(project.last_reminded_round, "manual")
            self.assertEqual(project.remind_count, 1)

    def test_mentioned_task_routed_to_person(self):
        # 物流项目里点名指派的任务应进被点名人（王宇彤）的个人消息
        self._seed_vemory("让雨桐完成备货和标签相关准备", owner="尤文静")
        self._seed_vemory("安排出货证书 UN38.3 鉴定报告", owner="尤文静")
        result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        projects = [s for s in result["sent"] if s.get("project")]
        persons = [s for s in result["sent"] if not s.get("project")]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["titles"], ["安排出货证书 UN38.3 鉴定报告"])
        person = [s for s in persons if s.get("owner") == "王宇彤"]
        self.assertEqual(len(person), 1)
        self.assertEqual(person[0]["titles"], ["让雨桐完成备货和标签相关准备"])


if __name__ == "__main__":
    unittest.main()
