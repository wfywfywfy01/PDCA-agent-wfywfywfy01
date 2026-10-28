"""Generic VPS task cards must preserve source isolation and fail closed."""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app import heiwu_tasks
from app.duzhan_admin import group_tasks, service, runtime
from app.models.duzhan_agent import DuzhanAgent
from app.models.pdca_task import PdcaTask
from app.models.scheduled_job_run import ScheduledJobRun

CHANNEL = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc)
MEMBERS = [
    {"member_type": "user", "user_id": 100, "employee_name": "发布人", "role": "admin"},
    {"member_type": "user", "user_id": 101, "employee_name": "同事甲", "role": "member"},
    {"member_type": "user", "user_id": 102, "employee_name": "同事乙", "role": "admin", "job_title": "数据分析"},
]
NOTICE = {"id": "notice", "sender_user_id": 100, "created_at": "2026-10-28T01:00:00Z", "body": "@所有人 今天完成客户复盘作业并提交", "message_type": "text"}


def card(**changes):
    blocks = [{"type": "group", "channel_id": CHANNEL, "label": "协作群"},
              {"type": "times", "slots": ["10:00", "20:00"]},
              {"type": "task_policy", "publisher_user_ids": [100], "excluded_user_ids": []}]
    return DuzhanAgent(id=90, name="群任务", enabled=True, timezone="Asia/Shanghai", blocks_json=json.dumps(blocks), **changes)


class GenericTaskTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch("app.database.get_engine", return_value=self.engine)
        self.engine_patch.start()
        self.ledger_patch = patch("app.scheduler.run_ledger.get_engine", return_value=self.engine)
        self.ledger_patch.start()
        self.settings = SimpleNamespace(scheduler_enabled=True, duzhan_bot_app_id="fixed-bot", duzhan_bot_app_secret="test-only", heiwu_channel_id="", heiwu_tasks_enabled=False, remote_db_from_host=False,
            heiwu_task_excluded_user_ids=(101,), heiwu_task_excluded_names=("同事乙",))
        self.settings_patch = patch("app.config.get_settings", return_value=self.settings)
        self.settings_patch.start()
        self.env_patch = patch.dict(os.environ, {"PDCA_DUZHAN_BOT_APP_ID": "fixed-bot", "PDCA_DUZHAN_BOT_APP_SECRET": "test-only"})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.settings_patch.stop()
        self.ledger_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()

    def rows(self):
        with Session(self.engine) as session:
            return list(session.exec(select(PdcaTask)).all())

    def directory_payload(self):
        return {"items": [{"channel_id": CHANNEL, "label": "协作群", "members": [{"user_id": row["user_id"], "name": row["employee_name"], "role": row["role"]} for row in MEMBERS], "bot_joined": True, "available": True, "reason": ""}], "configured": True, "bot_app_id": "fixed-bot"}

    def test_generic_card_is_valid_without_business_allowlist(self):
        self.assertEqual(service.validate_agent(card()), [])
        self.assertEqual(service.renderer_for(service.blocks_of(card())), "group_tasks")

    def test_invalid_publisher_ids_and_unsupported_rules_fail_validation(self):
        item = card()
        blocks = [{"type": "group", "channel_id": CHANNEL}, {"type": "times", "slots": ["10:00"]},
                  {"type": "task_policy", "publisher_user_ids": [True, -1, "100"], "excluded_user_ids": []},
                  {"type": "rule", "mode": "text", "text": "假装闭环"}]
        item.blocks_json = json.dumps(blocks)
        self.assertTrue(service.validate_agent(item))

    def test_invalid_draft_structure_preview_returns_errors_without_crashing(self):
        item = card()
        blocks = json.loads(item.blocks_json)
        blocks[2]["publisher_user_ids"] = None
        item.blocks_json = json.dumps(blocks)
        preview = service.preview_agent(item)
        self.assertTrue(preview["errors"])

    def test_explicit_generic_policy_does_not_inherit_heiwu_exclusions_or_jobs(self):
        policy = group_tasks.owner_policy(card())
        parsed = heiwu_tasks.parse_assignment_message(NOTICE, MEMBERS, publisher_user_id=100, policy=policy)
        self.assertEqual({row["owner_user_id"] for row in parsed}, {"101", "102"})
        self.assertEqual(heiwu_tasks.parse_assignment_message(NOTICE, MEMBERS, publisher_user_id=100), [])

    def test_exclusion_is_scoped_and_preserves_original_task(self):
        policy = group_tasks.owner_policy(card())
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=policy)
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=OTHER, publisher_user_id=100, policy=policy)
        excluded = heiwu_tasks.TaskPolicy(excluded_user_ids=(101,), exclude_admins=False, exclude_support=False)
        heiwu_tasks.sync_assignment_messages([], [], channel_id=CHANNEL, publisher_user_id=100, policy=excluded)
        rows = self.rows()
        self.assertEqual(sum(row.verification_status == "excluded" for row in rows), 1)
        self.assertTrue(all(row.status == "pending" for row in rows if row.group_channel_id == OTHER))
        self.assertTrue(all("assignment_notice" in row.evidence_json for row in rows))

    def test_directory_matches_fixed_sender_and_marks_missing_roster_unavailable(self):
        bot_rows = {"channels": [
            {"channel_id": CHANNEL, "channel_name": "协作群", "channel_type": "group", "app_id": "fixed-bot"},
            {"channel_id": OTHER, "channel_name": "不可读", "channel_type": "group", "app_id": "fixed-bot"},
            {"channel_id": "other-bot", "channel_type": "group", "app_id": "someone-else"},
        ]}
        with patch("app.vertu.client.run_vertu_sync_json", side_effect=[bot_rows, {"channels": [{"id": CHANNEL, "members": MEMBERS}]}]):
            result = group_tasks.group_options()
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["items"][0]["available"])
        self.assertFalse(result["items"][1]["available"])
        self.assertEqual(result["items"][0]["members"][0]["user_id"], 100)

    def test_enable_requires_current_members_and_configured_sender(self):
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()):
            self.assertEqual(group_tasks.connection_errors(card()), [])
            item = card()
            blocks = json.loads(item.blocks_json)
            blocks[2]["publisher_user_ids"] = [999]
            item.blocks_json = json.dumps(blocks)
            self.assertTrue(group_tasks.connection_errors(item))
        with patch.object(group_tasks, "group_options", return_value={"items": [], "configured": False}):
            self.assertTrue(group_tasks.connection_errors(card()))

    def test_generic_cards_never_enter_legacy_sales_schedule(self):
        with patch.object(runtime, "load_enabled_agents", return_value=[card()]):
            self.assertEqual(runtime.duzhan_agents(), [])
            self.assertEqual(runtime.follow_agents(), [])

    def test_preview_is_read_only_and_does_not_claim_or_fetch(self):
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=group_tasks.owner_policy(card()))
        before = [row.model_dump() for row in self.rows()]
        with patch.object(heiwu_tasks, "fetch_group_history", side_effect=AssertionError("preview fetched")), patch("app.vps_im_push.push_duzhan_message", side_effect=AssertionError("preview sent")), patch("app.scheduler.run_ledger.claim_run", side_effect=AssertionError("preview claimed")):
            result = service.render_preview(card(), day="2026-10-28", slot="10:00")
        self.assertTrue(result["ok"])
        self.assertIn("待确认", result["body"])
        self.assertEqual(before, [row.model_dump() for row in self.rows()])

    def test_run_collects_real_tasks_once_with_channel_scoped_keys(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        history = {"complete": True, "messages": [NOTICE], "coverage_start": datetime(2026, 10, 1, tzinfo=timezone.utc), "error": ""}
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()), patch.object(heiwu_tasks, "fetch_group_members", return_value={"complete": True, "members": MEMBERS, "error": ""}), patch.object(heiwu_tasks, "fetch_group_history", return_value=history), patch("app.vps_im_push.push_duzhan_message", return_value=True) as send:
            result = group_tasks.run_card(90, "10:00", now=NOW)
            repeated = group_tasks.run_card(90, "10:00", now=NOW)
        self.assertEqual(result["reminded"], 2)
        self.assertEqual(repeated["skipped"], "already_claimed")
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all(CHANNEL in call.kwargs["idempotency_key"] for call in send.call_args_list))

    def test_incomplete_history_never_sends_or_labels_missing(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        history = {"complete": False, "messages": [NOTICE], "coverage_start": NOW, "error": "timeout"}
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()), patch.object(heiwu_tasks, "fetch_group_history", return_value=history), patch.object(heiwu_tasks, "fetch_group_members", return_value={"complete": True, "members": MEMBERS}), patch("app.vps_im_push.push_duzhan_message") as send:
            result = group_tasks.run_card(90, "10:00", now=NOW)
        send.assert_not_called()
        self.assertEqual(result["reminded"], 0)
        self.assertTrue(result["failed"])
        self.assertEqual(self.rows(), [])

    def test_reserved_groups_cannot_be_taken_over_by_generic_cards(self):
        from app.duzhan import GROUPS
        from app.heiwu import channel_id
        for target in (GROUPS[0].channel_id, channel_id()):
            item = card()
            blocks = json.loads(item.blocks_json)
            blocks[0]["channel_id"] = target
            item.blocks_json = json.dumps(blocks)
            self.assertTrue(service.validate_agent(item))

    def test_api_drafts_are_off_and_enable_revalidates_group_access(self):
        from fastapi.testclient import TestClient
        from app.database import get_session
        from app.duzhan_admin.router import require_admin, router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        def session_dep():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = session_dep
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(role="admin", username="test")
        headers = {"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"}
        try:
            with TestClient(app, base_url="https://testserver") as client:
                with patch.object(group_tasks, "group_options", return_value=self.directory_payload()):
                    response = client.get("/api/duzhan-agents/group-options")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["items"][0]["channel_id"], CHANNEL)
                created = client.post("/api/duzhan-agents", headers=headers, json={"name": "新群", "blocks": json.loads(card().blocks_json)})
                self.assertEqual(created.status_code, 200, created.text)
                self.assertFalse(created.json()["enabled"])
                url = f"/api/duzhan-agents/{created.json()['id']}/toggle"
                with patch.object(group_tasks, "group_options", return_value={"configured": False, "items": []}):
                    self.assertEqual(client.post(url, headers=headers, json={"enabled": True}).status_code, 400)
                with patch.object(group_tasks, "group_options", return_value=self.directory_payload()):
                    enabled = client.post(url, headers=headers, json={"enabled": True})
                    self.assertEqual(enabled.status_code, 200, enabled.text)
                    self.assertTrue(enabled.json()["enabled"])
        finally:
            app.dependency_overrides.clear()

    def test_paused_during_collection_does_not_send(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        def history(*args, **kwargs):
            with Session(self.engine) as session:
                row = session.get(DuzhanAgent, 90)
                row.enabled = False
                session.add(row)
                session.commit()
            return {"complete": True, "messages": [NOTICE], "coverage_start": NOW, "error": ""}
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()), patch.object(heiwu_tasks, "fetch_group_history", side_effect=history), patch.object(heiwu_tasks, "fetch_group_members", return_value={"complete": True, "members": MEMBERS}), patch("app.vps_im_push.push_duzhan_message") as send:
            result = group_tasks.run_card(90, "10:00", now=NOW)
        send.assert_not_called()
        self.assertEqual(result["skipped"], "configuration_changed")

    def test_failed_delivery_never_marks_tasks_reminded(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        history = {"complete": True, "messages": [NOTICE], "coverage_start": datetime(2026, 10, 1, tzinfo=timezone.utc), "error": ""}
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()), patch.object(heiwu_tasks, "fetch_group_members", return_value={"complete": True, "members": MEMBERS}), patch.object(heiwu_tasks, "fetch_group_history", return_value=history), patch("app.vps_im_push.push_duzhan_message", return_value=False):
            result = group_tasks.run_card(90, "10:00", now=NOW)
        self.assertTrue(result["failed"])
        self.assertEqual(result["reminded"], 0)
        self.assertTrue(all(row.last_reminded_at is None for row in self.rows()))

    def test_two_publishers_coexist_and_edit_does_not_cancel_other_publisher(self):
        policy = group_tasks.owner_policy(card())
        members = MEMBERS + [{"member_type": "user", "user_id": 103, "employee_name": "发布人乙"}]
        eligible = [row for row in members if row["user_id"] not in {100, 103}]
        second = dict(NOTICE, id="notice-b", sender_user_id=103, body="@所有人 今天完成售后复盘任务并提交")
        heiwu_tasks.sync_assignment_messages([NOTICE, second], eligible, channel_id=CHANNEL, publisher_user_id=100, policy=policy)
        heiwu_tasks.sync_assignment_messages([NOTICE, second], eligible, channel_id=CHANNEL, publisher_user_id=103, policy=policy)
        self.assertEqual(len(self.rows()), 4)
        first_rows = [row.model_dump() for row in self.rows() if heiwu_tasks._source_message_id(row) == "notice"]
        changed = dict(second, body="同事甲：今天完成售后材料整理")
        heiwu_tasks.sync_assignment_messages([NOTICE, changed], eligible, channel_id=CHANNEL, publisher_user_id=103, policy=policy)
        self.assertEqual(first_rows, [row.model_dump() for row in self.rows() if heiwu_tasks._source_message_id(row) == "notice"])
        self.assertTrue(all(heiwu_tasks._assignment_record(row.evidence_json).get("publisher_user_id") in {"100", "103"} for row in self.rows()))

    def test_changed_publisher_does_not_show_old_assignment_as_current_preview(self):
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=group_tasks.owner_policy(card()))
        item = card()
        blocks = json.loads(item.blocks_json)
        blocks[2]["publisher_user_ids"] = [102]
        item.blocks_json = json.dumps(blocks)
        preview = group_tasks.render_preview(item, day="2026-10-28", slot="10:00")
        self.assertEqual(preview["task_count"], 0)

    def test_removing_generic_exclusion_resumes_task_without_losing_history(self):
        policy = group_tasks.owner_policy(card())
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=policy)
        excluded = heiwu_tasks.TaskPolicy(excluded_user_ids=(101,), exclude_admins=False, exclude_support=False)
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=excluded)
        self.assertEqual(sum(row.verification_status == "excluded" for row in self.rows()), 1)
        heiwu_tasks.sync_assignment_messages([NOTICE], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=policy)
        self.assertTrue(all(row.status == "pending" for row in self.rows()))
        self.assertTrue(any("owner_exclusion" in row.evidence_json for row in self.rows()))

    def test_generic_dedupe_distinguishes_same_name_accounts_and_publishers(self):
        policy = group_tasks.owner_policy(card())
        members = [dict(MEMBERS[1], user_id=101), dict(MEMBERS[1], user_id=102)]
        heiwu_tasks.sync_assignment_messages([NOTICE], members, channel_id=CHANNEL, publisher_user_id=100, policy=policy)
        second = dict(NOTICE, id="notice-2", sender_user_id=103)
        heiwu_tasks.sync_assignment_messages([second], members, channel_id=CHANNEL, publisher_user_id=103, policy=policy)
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual({(heiwu_tasks._assignment_record(row.evidence_json)["owner_user_id"], heiwu_tasks._assignment_record(row.evidence_json)["publisher_user_id"]) for row in self.rows()}, {("101", "100"), ("102", "100"), ("101", "103"), ("102", "103")})

    def test_older_long_term_assignment_remains_pending_and_reminded(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        old = dict(NOTICE, created_at="2026-09-01T01:00:00Z", body="@所有人 长期完成客户复盘作业并提交")
        heiwu_tasks.sync_assignment_messages([old], MEMBERS, channel_id=CHANNEL, publisher_user_id=100, policy=group_tasks.owner_policy(card()))
        history = {"complete": True, "messages": [], "coverage_start": datetime(2026, 10, 7, tzinfo=timezone.utc), "error": ""}
        with patch.object(group_tasks, "group_options", return_value=self.directory_payload()), patch.object(heiwu_tasks, "fetch_group_members", return_value={"complete": True, "members": MEMBERS}), patch.object(heiwu_tasks, "fetch_group_history", return_value=history), patch("app.vps_im_push.push_duzhan_message", return_value=True) as send:
            result = group_tasks.run_card(90, "10:00", now=NOW)
        self.assertEqual(result["pending"], 2)
        self.assertEqual(result["reminded"], 2)
        self.assertTrue(all("待人工确认" in call.args[0] for call in send.call_args_list))

    def test_poll_reads_saved_schedule_each_minute_and_honors_pause(self):
        with Session(self.engine) as session:
            session.add(card())
            session.commit()
        with patch.object(group_tasks, "run_card", return_value={"reminded": 0}) as run:
            group_tasks.poll_due(now=NOW)
            self.assertEqual(run.call_count, 1)
            with Session(self.engine) as session:
                row = session.get(DuzhanAgent, 90)
                row.enabled = False
                session.add(row)
                session.commit()
            group_tasks.poll_due(now=NOW)
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
