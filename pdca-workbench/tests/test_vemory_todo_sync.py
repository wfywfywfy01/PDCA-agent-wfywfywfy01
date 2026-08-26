# -*- coding: utf-8 -*-
"""Vemory 会议待办同步（事实源）单测。"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.pdca_task import PdcaTask
from app.todos import vemory as vmemory
from app.todos.service import list_pending_tasks

USERS = [
    {"name": "何海文", "vemoryUserId": 109, "vpsUserId": 14113},
    {"name": "杨晶晶", "vemoryUserId": 69, "vpsUserId": 13122},
]


def _fake_response(status_code=200, payload=None, text=""):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    return FakeResponse()


def _meeting(meeting_id="m1", name="项目周会", ts_ms=None):
    ts = ts_ms or int(datetime.now().timestamp() * 1000)
    return {"meeting_id": meeting_id, "meeting_name": name, "start_record_time": ts, "todos": []}


class VemorySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "vemory-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.todos.vemory.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.patch_key = patch.dict(os.environ, {"VEMORY_OPENAPI_KEY": "test-key"})
        self.patch_key.start()
        self.patch_users = patch(
            "app.todos.vemory.load_vemory_users", return_value=USERS
        )
        self.patch_users.start()

    def tearDown(self):
        self.patch_users.stop()
        self.patch_key.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    # ── 名单解析（setUp 已 mock，先恢复真实函数再测） ──
    def test_load_users_formats(self):
        self.patch_users.stop()
        try:
            self.assertEqual(len(vmemory.load_vemory_users('[{"name":"甲","vemoryUserId":1}]')), 1)
            self.assertEqual(
                len(vmemory.load_vemory_users('{"people":[{"name":"甲","vemoryUserId":1}]}')), 1
            )
            self.assertEqual(vmemory.load_vemory_users("not json"), [])
            # 空 raw 会回退到环境配置的名单；显式空数组才是真空名单
            self.assertEqual(vmemory.load_vemory_users("[]"), [])
            self.assertEqual(
                vmemory.load_vemory_users('[{"name":"无ID"}]'), []  # 无 ID 视为无效
            )
        finally:
            self.patch_users.start()

    def test_external_id(self):
        self.assertEqual(vmemory._external_id({"id": 42}, 1), "vemory:42")
        fallback = vmemory._external_id({"_meeting": {"meeting_id": "m1"}, "content": "x"}, 1)
        self.assertTrue(fallback.startswith("vemory-hash:"))
        self.assertEqual(len(fallback), len("vemory-hash:") + 20)

    # ── 接口调用 ──
    def test_fetch_ok_and_flat(self):
        meeting = _meeting()
        meeting["todos"] = [
            {"id": 1, "content": "完成联调", "status": 0, "deadline": "2026-08-25"},
            {"id": 2, "content": "确认窗口", "status": 1, "deadline": ""},
        ]
        body = {"status": 0, "data": {"meetings": [meeting, _meeting("m2", "无待办会")]}}
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured.update(url=url, json=json, headers=headers, timeout=timeout)
            return _fake_response(200, body)

        with patch("app.todos.vemory.httpx.post", side_effect=fake_post):
            todos = vmemory.fetch_vemory_todos(
                USERS[0], "key-1", "https://vemory-meet.vemory.io", "2026-08-14 00:00:00", "2026-08-20 23:59:59"
            )
        self.assertEqual(len(todos), 2)  # 无待办会议不产生条目
        self.assertEqual(todos[0]["_meeting"]["meeting_name"], "项目周会")
        self.assertEqual(captured["json"]["user_id"], 109)
        self.assertEqual(captured["json"]["timezone"], "Asia/Shanghai")
        self.assertEqual(captured["headers"]["X-API-Key"], "key-1")

    def test_fetch_errors(self):
        with patch("app.todos.vemory.httpx.post", return_value=_fake_response(401, {"status": 1, "err_code": "OPENAPI_KEY_INVALID"})):
            with self.assertRaises(RuntimeError):
                vmemory.fetch_vemory_todos(USERS[0], "k", "u", "s", "e")
        with patch("app.todos.vemory.httpx.post", return_value=_fake_response(200, {"status": 1, "err_code": "USER_NOT_FOUND"})):
            with self.assertRaises(RuntimeError) as ctx:
                vmemory.fetch_vemory_todos(USERS[0], "k", "u", "s", "e")
            self.assertIn("USER_NOT_FOUND", str(ctx.exception))
        with patch("app.todos.vemory.httpx.post", return_value=_fake_response(200, None)):
            with self.assertRaises(RuntimeError):
                vmemory.fetch_vemory_todos(USERS[0], "k", "u", "s", "e")

    # ── 同步落库 ──
    def _sync(self, todos_by_user):
        def fake_fetch(user, api_key, url, start_time, end_time):
            return todos_by_user.get(user["name"], [])

        with patch("app.todos.vemory.fetch_vemory_todos", side_effect=fake_fetch):
            return vmemory.sync_vemory_todos()

    def _rows(self):
        with Session(self.engine) as session:
            return list(session.exec(select(PdcaTask)).all())

    def test_sop_convergence_business_domain(self):
        meeting = _meeting("m1", "周会")
        todo = {"id": 20, "content": "给客户发 PI 确认交期", "status": 0, "deadline": "", "_meeting": meeting}
        self._sync({"何海文": [todo]})
        row = self._rows()[0]
        self.assertEqual(row.owner, "冯磊")  # 商务岗单人 → 冯磊
        self.assertEqual(row.position, "海外商务")
        self.assertEqual(row.origin_owner, "何海文")

    def test_sop_convergence_speaker_logistics(self):
        meeting = _meeting("m1", "周会")
        todo = {"id": 21, "content": "安排备货发货", "status": 0, "deadline": "", "speaker": "鲜娜", "_meeting": meeting}
        self._sync({"何海文": [todo]})
        row = self._rows()[0]
        self.assertEqual(row.position, "海外物流")
        self.assertEqual(row.owner, "鲜娜")

    def test_sop_convergence_fallback_participant(self):
        meeting = _meeting("m1", "周会")
        todo = {"id": 22, "content": "再约个时间", "status": 0, "deadline": "", "_meeting": meeting}
        self._sync({"何海文": [todo]})
        row = self._rows()[0]
        self.assertEqual(row.position, "unclassified")
        self.assertEqual(row.owner, "何海文")  # 定不了人 → 参与人本人
        self.assertEqual(row.origin_owner, "何海文")

    def test_skip_without_key_and_users(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VEMORY_OPENAPI_KEY", None)
            self.assertEqual(vmemory.sync_vemory_todos()["status"], "skipped")
        os.environ["VEMORY_OPENAPI_KEY"] = "test-key"
        with patch("app.todos.vemory.load_vemory_users", return_value=[]):
            self.assertEqual(vmemory.sync_vemory_todos()["status"], "skipped")

    def test_upsert_basic_fields(self):
        meeting = _meeting("m1", "项目周会")
        meeting["todos"] = [{"id": 7, "content": "完成接口联调", "status": 0, "deadline": "2026-08-25"}]
        result = self._sync({"何海文": [{"id": 7, "content": "完成接口联调", "status": 0, "deadline": "2026-08-25", "_meeting": meeting}]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["upserted"], 1)
        row = self._rows()[0]
        self.assertEqual(row.external_todo_id, "vemory:7")
        self.assertEqual(row.task_date, "2026-08-25")
        self.assertEqual(row.owner, "何海文")
        self.assertEqual(row.source, "vemory")
        self.assertEqual(row.meeting_name, "项目周会")
        self.assertEqual(row.status, "pending")

    def test_no_deadline_falls_back_to_meeting_date(self):
        meeting = _meeting("m1", "周会", ts_ms=int(datetime(2026, 8, 16, 2, 0, 0).timestamp() * 1000))
        todo = {"id": 8, "content": "推进迈凯伦报价", "status": 0, "deadline": "", "_meeting": meeting}
        self._sync({"何海文": [todo]})
        row = self._rows()[0]
        self.assertEqual(row.task_date, "2026-08-16")  # UTC 2026-08-15 18:00 → 沪 08-16
        self.assertEqual(row.meeting_date, "2026-08-16")

    def test_vemory_authoritative_status_and_deadline(self):
        meeting = _meeting("m1", "周会")
        todo = {"id": 9, "content": "事项A", "status": 0, "deadline": "2026-08-25", "_meeting": meeting}
        self._sync({"何海文": [todo]})
        # 用户在 workbench 手工改成 done，但 Vemory 仍为未完成 → 以 Vemory 为准改回 pending
        with Session(self.engine) as session:
            row = session.exec(select(PdcaTask)).all()[0]
            row.status = "done"
            session.add(row)
            session.commit()
        todo["deadline"] = "2026-08-27"
        self._sync({"何海文": [todo]})
        with Session(self.engine) as session:
            rows = session.exec(select(PdcaTask)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "pending")
        self.assertEqual(rows[0].task_date, "2026-08-27")
        # Vemory 标记完成 → 库内 done
        todo["status"] = 1
        result = self._sync({"何海文": [todo]})
        self.assertEqual(result["done_flipped"], 1)
        with Session(self.engine) as session:
            rows = session.exec(select(PdcaTask)).all()
        self.assertEqual(rows[0].status, "done")

    def test_deleted_in_window_closed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        in_window = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        out_window = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date=in_window, title="窗口内被删", owner="何海文", status="pending",
                source="vemory", external_todo_id="vemory:100", meeting_date=in_window,
            ))
            session.add(PdcaTask(
                task_date=out_window, title="窗口外老待办", owner="何海文", status="pending",
                source="vemory", external_todo_id="vemory:101", meeting_date=out_window,
            ))
            session.commit()
        result = self._sync({})  # 接口不再返回这两条
        self.assertEqual(result["deleted_closed"], 1)
        with Session(self.engine) as session:
            rows = {r.external_todo_id: r for r in session.exec(select(PdcaTask)).all()}
        self.assertEqual(rows["vemory:100"].status, "done")
        self.assertEqual(rows["vemory:101"].status, "pending")  # 窗口外不动

    def test_per_user_error_collected(self):
        def fake_fetch(user, api_key, url, start_time, end_time):
            if user["name"] == "杨晶晶":
                raise RuntimeError("HTTP 500")
            return []

        with patch("app.todos.vemory.fetch_vemory_todos", side_effect=fake_fetch):
            result = vmemory.sync_vemory_todos()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("杨晶晶", result["errors"][0])


class VemoryGraceTests(unittest.TestCase):
    """催办引擎对 Vemory 无截止待办的宽限期。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "grace-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.todos.service.get_engine", return_value=self.engine)
        self.patch_engine.start()

    def tearDown(self):
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, **kwargs):
        with Session(self.engine) as session:
            row = PdcaTask(**kwargs)
            session.add(row)
            session.commit()

    def test_grace_rule(self):
        today = datetime.now().strftime("%Y-%m-%d")
        recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        aged = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        # 无截止：会议=昨天 → 48h 宽限内不催
        self._seed(task_date=recent, title="刚开的会", owner="何海文", status="pending",
                   source="vemory", meeting_date=recent)
        # 无截止：会议=3 天前 → 超过宽限，催
        self._seed(task_date=aged, title="老会议", owner="何海文", status="pending",
                   source="vemory", meeting_date=aged)
        # 有截止且已逾期 → 不受宽限影响，催
        self._seed(task_date=aged, title="截止逾期", owner="何海文", status="pending",
                   source="vemory", meeting_date=recent)
        # 普通来源（非 vemory）不受宽限影响
        self._seed(task_date=recent, title="普通待办", owner="何海文", status="pending")
        titles = {row.title for row in list_pending_tasks(today)}
        self.assertNotIn("刚开的会", titles)
        self.assertIn("老会议", titles)
        self.assertIn("截止逾期", titles)
        self.assertIn("普通待办", titles)


if __name__ == "__main__":
    unittest.main()
