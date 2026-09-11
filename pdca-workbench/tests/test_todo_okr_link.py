# -*- coding: utf-8 -*-
"""待办/项目 ↔ 个人 OKR 挂接单测。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.todos.okr_link import link_tasks_and_projects


class FakeSettings:
    todo_remind_skip_owners: list[str] = []
    todo_owner_aliases: dict[str, str] = {}
    todo_okr_link_enabled = True


CATALOG = [
    {
        "id": "o1",
        "title": "对齐：经销商二部客户源200个，触达60个@杨晶晶组",
        "krs": [],
        "dept": "经销商二部",
        "employee": "何海文",
    },
    {
        "id": "o2",
        "title": "经销商PDCA/VPS/Vemory使用",
        "krs": ["完善PDCA操作台/使用，账号完善@付汪阳@所有经销商"],
        "dept": "海外渠道",
        "employee": "",
    },
    {
        "id": "o3",
        "title": "经销商二部业绩目标 2650000.00元",
        "krs": ["经销商二部业绩目标 2650000.00元"],
        "dept": "经销商二部",
        "employee": "",
    },
]


class OkrLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "okrlink-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.okr_link.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_settings = patch(
            "app.todos.okr_link.get_settings", return_value=FakeSettings()
        )
        self.patch_settings.start()
        self.patch_catalog = patch(
            "app.todos.okr_link.fetch_okr_catalog", return_value=CATALOG
        )
        self.mock_catalog = self.patch_catalog.start()

    def tearDown(self):
        self.patch_catalog.stop()
        self.patch_settings.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_tasks_and_project_linked_to_okr(self):
        with Session(self.engine) as session:
            proj = TodoProject(
                key="mtg:india", name="印度客户拓展", kind="meeting",
                status="跟进中", executors="[]", coordinator="",
            )
            session.add(proj)
            session.commit()
            session.refresh(proj)
            t1 = PdcaTask(
                task_date="2026-09-10", title="继续触达和约会印度名单中的客户",
                owner="何海文", status="pending", source="vemory",
                meeting_name="晨会", project_id=proj.id,
            )
            t2 = PdcaTask(
                task_date="2026-09-10", title="催促印度客户创建账号",
                owner="何海文", status="pending", source="vemory",
                meeting_name="晨会", project_id=proj.id,
            )
            session.add(t1)
            session.add(t2)
            session.commit()
            proj_id = proj.id
            t1_id = t1.id
            t2_id = t2.id

        result = link_tasks_and_projects()
        self.assertTrue(result["ok"])
        with Session(self.engine) as session:
            r1 = session.get(PdcaTask, t1_id)
            r2 = session.get(PdcaTask, t2_id)
            p = session.get(TodoProject, proj_id)
        self.assertIn("客户源", r1.okr_title)
        self.assertIn("PDCA", r2.okr_title)
        self.assertIn("客户源", p.okr_title)  # 项目取主流 OKR

    def test_fallback_to_dept_okr(self):
        # 无关键词命中的碎片 → 落到部门客户源/业绩 OKR
        with Session(self.engine) as session:
            task = PdcaTask(
                task_date="2026-09-09", title="跟进越南经销商资质文件",
                owner="于冰", status="pending", source="vemory",
                meeting_name="晨会",
            )
            session.add(task)
            session.commit()
            task_id = task.id
        catalog = CATALOG + [
            {
                "id": "o4",
                "title": "经销商一部客户源100个，触达20个@于冰组",
                "krs": [],
                "dept": "经销商一部",
                "employee": "",
            }
        ]
        self.mock_catalog.return_value = catalog
        link_tasks_and_projects()
        with Session(self.engine) as session:
            row = session.get(PdcaTask, task_id)
        self.assertIn("客户源", row.okr_title)


if __name__ == "__main__":
    unittest.main()
