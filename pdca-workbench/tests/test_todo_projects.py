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
from app.models.im_replies import ImRemindSend  # noqa: F401 — 保证 create_all 建 im_remind_sends 表
from app.todos.projects import (
    PROJECT_RULES,
    auto_close_meeting_projects,
    ensure_meeting_project,
    ensure_projects,
    match_project,
    normalize_meeting_topic,
)
from app.todos.service import build_project_message, run_todo_reminders


class MeetingTopicTests(unittest.TestCase):
    def test_normalize_meeting_topic(self):
        self.assertEqual(
            normalize_meeting_topic("2026-08-17 越南门店与代理策略同步会"),
            "越南门店与代理策略",
        )
        self.assertEqual(
            normalize_meeting_topic("2026-08-17 海外业绩复盘与规则化推进会议"),
            "海外业绩复盘与规则化推进",
        )
        self.assertEqual(
            normalize_meeting_topic("Virtue and Landmark 第一次会议(杨晶晶&何海文)"),
            "Virtue and Landmark",
        )
        self.assertEqual(
            normalize_meeting_topic("2026-08-19 多区域业务进展与收款跟进"),
            "多区域业务进展与收款",
        )
        self.assertEqual(
            normalize_meeting_topic("Sales Target Tracking, Regional Project Proposals, and Contract Closed-Loop Management Meeting"),
            "Sales Target Tracking, Regional Project Proposals, and Contract Closed-Loop Management",
        )
        # 无日期前缀/无后缀的原文保持
        self.assertEqual(
            normalize_meeting_topic("汽车改装项目设计方案与出海合作路径研讨"),
            "汽车改装项目设计方案与出海合作路径",
        )
        # 归一化后为空 → 回退去日期原文（避免项目名为空）
        self.assertEqual(normalize_meeting_topic("2026-08-20 会"), "会")
        self.assertEqual(normalize_meeting_topic(""), "")

    def test_meeting_project_stable_key_and_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'm.sqlite'}")
            SQLModel.metadata.create_all(engine)
            try:
                with Session(engine) as session:
                    p1 = ensure_meeting_project(session, "2026-08-17 越南门店与代理策略同步会")
                    p2 = ensure_meeting_project(session, "2026-08-25 越南门店与代理策略同步会")
                    self.assertIsNotNone(p1)
                    self.assertEqual(p1.id, p2.id)  # 同主题合并
                    self.assertEqual(p1.kind, "meeting")
                    self.assertEqual(p1.name, "越南门店与代理策略")
                    self.assertIsNone(ensure_meeting_project(session, ""))
            finally:
                engine.dispose()

    def test_auto_close_and_members(self):
        from app.todos.projects import refresh_meeting_project_members

        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'c.sqlite'}")
            SQLModel.metadata.create_all(engine)
            try:
                with Session(engine) as session:
                    p = ensure_meeting_project(session, "2026-08-17 越南门店与代理策略同步会")
                    session.add(PdcaTask(
                        task_date="2026-08-17", title="事项A", owner="杨晶晶",
                        status="done", project_id=p.id,
                    ))
                    session.add(PdcaTask(
                        task_date="2026-08-17", title="事项B", owner="刘春梅",
                        status="pending", project_id=p.id,
                    ))
                    session.commit()
                    self.assertEqual(auto_close_meeting_projects(session), 0)
                    self.assertEqual(refresh_meeting_project_members(session), 1)
                    session.flush()  # 先落库，refresh 才能看到成员刷新结果
                    session.refresh(p)
                    self.assertEqual(json.loads(p.executors), ["刘春梅", "杨晶晶"])
                    # 全部完成 → 自动闭环
                    for task in session.exec(select(PdcaTask)).all():
                        task.status = "done"
                        session.add(task)
                    session.commit()
                    self.assertEqual(auto_close_meeting_projects(session), 1)
                    session.flush()
                    session.refresh(p)
                    self.assertEqual(p.status, "已闭环")
                    # 重开：新待办挂入已闭环会议项目 → 跟进中，且不再被自动闭环
                    p.status = "跟进中"
                    session.add(p)
                    session.add(PdcaTask(
                        task_date="2026-08-17", title="事项C", owner="杨晶晶",
                        status="pending", project_id=p.id,
                    ))
                    session.commit()
                    self.assertEqual(auto_close_meeting_projects(session), 0)
            finally:
                engine.dispose()

    def test_build_project_message_card(self):
        project = TodoProject(
            key="mtg:test", name="越南门店与代理策略", kind="meeting",
            status="跟进中", executors="[]", coordinator="",
        )
        body = build_project_message(
            project, "杨晶晶",
            [PdcaTask(task_date="2026-08-17", title="给大家写一封邮件", owner="杨晶晶", status="pending")],
            today="2026-08-28", entry_url="https://example/app/",
            evidence_checked=False,
            open_total=5, done_total=3,
        )
        self.assertIn("【PDCA 项目待办】越南门店与代理策略", body)
        self.assertIn("状态：跟进中", body)
        self.assertIn("项目未完成 5 项（已完成 3 项）", body)
        self.assertIn("你名下还有 1 项未完成", body)
        self.assertIn("[逾期 2026-08-17] 给大家写一封邮件", body)


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

    def test_project_message_split_by_owner(self):
        # 项目消息按人拆分：每人只收自己名下的条目
        self._seed_vemory("印度独代谈判：整理总代框架", owner="何海文")
        self._seed_vemory("印度总代保证金条款确认", owner="杨晶晶")
        result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        self.assertEqual(len(result["sent"]), 2)
        by_owner = {s["owner"]: s for s in result["sent"]}
        self.assertEqual(by_owner["何海文"]["project"], "印度总代/独代谈判")
        self.assertEqual(by_owner["何海文"]["titles"], ["印度独代谈判：整理总代框架"])
        self.assertEqual(by_owner["杨晶晶"]["titles"], ["印度总代保证金条款确认"])
        self.assertIn("你名下", by_owner["何海文"]["preview"])

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
        self.assertEqual(projects[0]["owner"], "尤文静")
        self.assertEqual(projects[0]["titles"], ["安排出货证书 UN38.3 鉴定报告"])
        person = [s for s in persons if s.get("owner") == "王宇彤"]
        self.assertEqual(len(person), 1)
        self.assertEqual(person[0]["titles"], ["让雨桐完成备货和标签相关准备"])


if __name__ == "__main__":
    unittest.main()
