# -*- coding: utf-8 -*-
"""每日催收简报单测：分类统计与升级链名单。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.pdca_task import PdcaTask
from app.todos.brief import build_daily_brief


class FakeSettings:
    todo_remind_skip_owners: list[str] = []
    todo_owner_aliases: dict[str, str] = {}


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "brief-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.brief.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_settings = patch(
            "app.todos.brief.get_settings", return_value=FakeSettings()
        )
        self.patch_settings.start()

    def tearDown(self):
        self.patch_settings.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, **kwargs):
        defaults = {
            "task_date": datetime.now().strftime("%Y-%m-%d"),
            "title": "待办",
            "owner": "张三",
            "status": "pending",
        }
        defaults.update(kwargs)
        with Session(self.engine) as session:
            row = PdcaTask(**defaults)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def test_classified_brief_and_escalation(self):
        today = datetime.now().strftime("%Y-%m-%d")
        # 张三：1 有回复 + 1 无回复且催过 3 次 → 升级
        self._seed(title="在做的", owner="张三",
                   replied_at=datetime.utcnow(), reply_text="推进中")
        no_reply = self._seed(title="没动静", owner="张三")
        no_reply.remind_count = 3
        with Session(self.engine) as session:
            session.add(no_reply)
            session.commit()
        # 张三：近 7 天完成 1 条
        self._seed(title="已办完", owner="张三", status="done")
        # 李四：1 无回复但只催过 1 次 → 不升级
        li = self._seed(title="刚开始", owner="李四")
        li.remind_count = 1
        with Session(self.engine) as session:
            session.add(li)
            session.commit()

        body = build_daily_brief(today)
        self.assertIn("张三", body)
        self.assertIn("有进度 1 / 无回复 1", body)
        self.assertIn("近7天完成 1", body)
        self.assertIn("建议线下约谈", body)
        self.assertIn("张三", body.split("升级提醒")[-1])
        self.assertNotIn("李四", body.split("升级提醒")[-1])


if __name__ == "__main__":
    unittest.main()
