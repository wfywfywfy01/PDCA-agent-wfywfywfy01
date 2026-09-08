# -*- coding: utf-8 -*-
"""负责人拆分（A&B）、静态 user_id 映射与相关路由/认领/打分单测。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

import app.todos.evidence as evidence_mod
from app.models.pdca_task import PdcaTask
from app.todos.owners import split_owners


class FakeSettings:
    workbench_base_url = "https://example/app/"
    todo_remind_grace_hours = 48
    todo_remind_skip_owners: list[str] = []
    todo_bot_app_id = ""
    todo_user_id_overrides: dict[str, int] = {}
    todo_owner_aliases: dict[str, str] = {}
    todo_group_channel_id = ""
    todo_group_notice_enabled = False
    todo_group_notice_min_date = ""
    todo_ledger_doc_id = ""


class SplitOwnersTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(split_owners("徐华俊"), ["徐华俊"])
        self.assertEqual(split_owners("  徐华俊 "), ["徐华俊"])
        self.assertEqual(split_owners(""), [])

    def test_combined(self):
        self.assertEqual(split_owners("谢涛&Sissi"), ["谢涛", "Sissi"])
        self.assertEqual(split_owners("Jim＆Sissi"), ["Jim", "Sissi"])
        self.assertEqual(split_owners("Sissi&徐豪"), ["Sissi", "徐豪"])
        self.assertEqual(split_owners("A& B &C"), ["A", "B", "C"])


class OverrideResolveTests(unittest.TestCase):
    def test_override_wins_without_org_search(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None
        with patch("app.todos.service.get_settings") as mock_settings, \
                patch("app.todos.service.run_vertu_sync_json") as mock_json:
            mock_settings.return_value.todo_user_id_overrides = {"徐豪": 12665}
            from app.todos.service import resolve_im_user

            user = resolve_im_user("徐豪", {})
            self.assertEqual(user, {"user_id": 12665, "name": "徐豪"})
            mock_json.assert_not_called()  # 映射命中不查 IM

    def test_no_override_falls_through(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None

        def fake_json(args, timeout):
            if "+users" in args:
                return {"ok": True, "count": 0, "users": []}
            if "+channels" in args:
                return {"channels": []}
            if "+me" in args:
                return {"ok": True, "user": {"userId": 13365}}
            return None

        with patch("app.todos.service.get_settings") as mock_settings, \
                patch("app.todos.service.run_vertu_sync_json", side_effect=fake_json):
            mock_settings.return_value.todo_user_id_overrides = {}
            from app.todos.service import resolve_im_user

            user = resolve_im_user("查无此人", {})
            self.assertIsNone(user)


class CombinedOwnerRoutingTests(unittest.TestCase):
    """「A&B」合并负责人：任务拆到每个人名下发送；查不到的单独跳过。"""

    def setUp(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None
        service_mod._CHANNELS_SCAN = {"ts": 0.0, "map": {}}
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "owners-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_outbox = patch("app.todos.service._write_outbox", lambda result: None)
        self.patch_outbox.start()
        evidence_mod._CORPUS_CACHE.clear()
        self.patch_evidence = patch(
            "app.todos.evidence.run_vertu_sync", return_value=(1, "", "offline")
        )
        self.patch_evidence.start()
        self.patch_send = patch(
            "app.todos.service.run_vertu_sync", return_value=(0, "", "")
        )
        self.mock_send = self.patch_send.start()

        def fake_users(args, timeout):
            if "+me" in args:
                return {"ok": True, "user": {"userId": 999}}
            if "+channels" in args:
                return {"channels": []}
            query = args[args.index("--query") + 1]
            if query == "谢涛":
                return [{"user_id": 14529, "name": "谢涛"}]
            return {"ok": True, "count": 0, "users": []}

        self.patch_json = patch(
            "app.todos.service.run_vertu_sync_json", side_effect=fake_users
        )
        self.patch_json.start()
        self.fake_settings = FakeSettings()
        self.fake_settings.todo_user_id_overrides = {"徐豪": 12665}
        self.patch_settings = patch(
            "app.todos.service.get_settings", return_value=self.fake_settings
        )
        self.patch_settings.start()

    def tearDown(self):
        import app.todos.service as service_mod

        service_mod._SELF_USER_ID = None
        self.patch_settings.stop()
        self.patch_json.stop()
        self.patch_send.stop()
        self.patch_evidence.stop()
        self.patch_outbox.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_combined_owner_split_routing(self):
        from app.todos.service import run_todo_reminders

        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date=today, title="落地签署协议", owner="谢涛&Sissi",
                status="pending", source="followup-table",
            ))
            session.add(PdcaTask(
                task_date=today, title="完成实地考察", owner="Sissi&徐豪",
                status="pending", source="followup-table",
            ))
            session.commit()
        result = run_todo_reminders(round_label="manual", force=True, dry_run=True)
        by_owner = {s["owner"]: s["titles"] for s in result["sent"]}
        self.assertIn("谢涛", by_owner)
        self.assertIn("落地签署协议", by_owner["谢涛"])
        self.assertIn("徐豪", by_owner)
        self.assertIn("完成实地考察", by_owner["徐豪"])
        # Sissi 组织里查不到 → 单独跳过并报告
        reasons = {s["owner"]: s["reason"] for s in result["skipped_owners"]}
        self.assertEqual(reasons.get("Sissi"), "im_user_not_found")


class CombinedOwnerClaimTests(unittest.TestCase):
    """任一共有人认领即视为该条已认领。"""

    def setUp(self):
        import app.todos.claims as claims_mod

        claims_mod.USER_ID_CACHE.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "owners-claim.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.claims.get_engine", return_value=self.engine
        )
        self.patch_engine.start()

        def fake_json(args, timeout):
            if "+history" in args:
                return {
                    "messages": [
                        {"id": "m1", "sender_user_id": 12345, "body": "收到"},
                    ]
                }
            if "+personnel-info" in args:
                return {"rows": [{"name": "Sissi"}]}
            return None

        self.patch_json = patch(
            "app.todos.claims.run_vertu_sync_json", side_effect=fake_json
        )
        self.patch_json.start()
        self.fake_settings = FakeSettings()
        self.fake_settings.todo_group_channel_id = "group-1"
        self.patch_settings = patch(
            "app.todos.claims.get_settings", return_value=self.fake_settings
        )
        self.patch_settings.start()

    def tearDown(self):
        self.patch_settings.stop()
        self.patch_json.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_claim_by_part_marks_combined_task(self):
        from app.todos.claims import collect_group_claims

        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            combined = PdcaTask(
                task_date=today, title="初稿+评审", owner="Jim&Sissi",
                status="pending", source="followup-table",
            )
            solo = PdcaTask(
                task_date=today, title="Jim 个人事项", owner="Jim",
                status="pending", source="followup-table",
            )
            session.add(combined)
            session.add(solo)
            session.commit()
            combined_id = combined.id
            solo_id = solo.id
        result = collect_group_claims(today)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claimed_people"][0]["owner"], "Sissi")
        with Session(self.engine) as session:
            combined_row = session.get(PdcaTask, combined_id)
            solo_row = session.get(PdcaTask, solo_id)
        self.assertIsNotNone(combined_row.claimed_at)  # Sissi 认领 → 共同条目已认领
        self.assertIsNone(solo_row.claimed_at)  # 纯 Jim 条目不受影响

    def test_claim_via_alias_marks_alias_tasks(self):
        """丁晓茜认领 == Sissi 名下待办也认领（别名口径）。"""
        from app.todos.claims import collect_group_claims

        today = datetime.now().strftime("%Y-%m-%d")
        with Session(self.engine) as session:
            task = PdcaTask(
                task_date=today, title="汽车落地签署", owner="Sissi",
                status="pending", source="followup-table",
            )
            session.add(task)
            session.commit()
            task_id = task.id
        self.fake_settings.todo_owner_aliases = {"sissi": "丁晓茜"}

        def fake_json(args, timeout):
            if "+history" in args:
                return {
                    "messages": [
                        {"id": "m9", "sender_user_id": 14519, "body": "收到"},
                    ]
                }
            if "+personnel-info" in args:
                return {"rows": [{"name": "丁晓茜"}]}
            return None

        with patch("app.todos.claims.run_vertu_sync_json", side_effect=fake_json):
            result = collect_group_claims(today)
        self.assertEqual(result["claimed_people"][0]["owner"], "丁晓茜")
        with Session(self.engine) as session:
            row = session.get(PdcaTask, task_id)
        self.assertIsNotNone(row.claimed_at)


if __name__ == "__main__":
    unittest.main()
