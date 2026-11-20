"""Real-only source-task reminders must fail closed and never invent progress."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.duzhan_admin import acquisition_chase as chase


NOW = datetime(2026, 11, 18, 10, 30, tzinfo=timezone.utc)
GROUP = "11111111-1111-4111-8111-111111111111"
DISPATCH = "22222222-2222-4222-8222-222222222222"
TARGET = dict(owner_user_id=4, vps_user_id=101, channel_id=GROUP, dispatch_message_id=DISPATCH)


def payload(count=1):
    counts = dict(records=count, open=count, completed=0, actionable=count, overdue=count,
                  unaccepted=count, no_progress=count, missing_due=0, missing_next_action=0,
                  pending_reply=0, reply_processing=0)
    task = dict(task_id=1, owner_user_id=4, owner_name="测试负责人", display_name="私有客户",
                route="partner_site", source_system="report_catalog", report_id=None,
                status="pending", stage="pending", accepted_at=None, last_progress_at=None,
                last_progress=None, company_id=None, customer_stage=None,
                customer_stage_status="unlinked", customer_stage_event_id=None,
                customer_stage_at=None, next_due_at=(NOW-timedelta(hours=1)).isoformat(),
                next_action="核实联系人并回写", overdue=True, unaccepted=True, no_progress=True,
                missing_due=False, missing_next_action=False, pending_reply=False,
                reply_processing=False, signals=["overdue"], pending_reply_count=0,
                processing_reply_count=0, pending_replies=[], pending_replies_truncated=False,
                stored_outreach_hold=False, outreach_hold_status="not_checked")
    page = dict(as_of=NOW.isoformat(), total=count, limit=100, offset=0, has_more=False)
    return dict(ok=True, data=dict(environment="real", as_of=NOW.isoformat(),
        items=[], by_owner=[], truncated=False,
        source_tasks=dict(**page, unit="source_task", totals=counts,
                          by_owner=[dict(owner_user_id=4, owner_name="测试负责人", **counts)],
                          items=[dict(task, task_id=i+1) for i in range(count)]),
        owner_pending_replies=dict(**dict(page, total=0), unit="vps_message", by_owner=[], items=[])))


class AcquisitionChaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(environment="production", scheduler_enabled=True,
            remote_db_from_host=False, acquisition_chase_enabled=True,
            acquisition_chase_targets=json.dumps([TARGET]),
            acquisition_supervision_url="https://gtm.example.test/gtm",
            acquisition_supervision_token="x"*32)
        self.data = payload()
        self.patches = [
            patch("app.config.get_settings", return_value=self.settings),
            patch("app.scheduler.run_ledger.get_engine", return_value=self.engine),
            patch.object(chase, "get_settings", return_value=self.settings),
            patch.object(chase, "verified_recipients", return_value={4}),
            patch.object(chase.httpx, "Client"),
            patch.object(chase, "push_duzhan_message", return_value=True),
        ]
        self.started = [p.start() for p in self.patches]
        self.client = self.started[-2].return_value.__enter__.return_value
        self.send = self.started[-1]
        self.client.get.side_effect = lambda *a, **k: httpx.Response(
            200, request=httpx.Request("GET", "https://gtm.example.test/gtm"), json=self.data)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()

    def task(self):
        return self.data["data"]["source_tasks"]["items"][0]

    def test_real_overdue_once_per_owner_day_and_original_quote(self):
        result = chase.poll_due(now=NOW)
        self.assertEqual(result["sent"], 1)
        body, group = self.send.call_args.args
        self.assertEqual(group, GROUP)
        self.assertIn("线索 #1", body)
        self.assertIn("原派单", body)
        self.assertNotIn("私有客户", body)
        self.assertNotIn("?", body)
        self.assertEqual(self.send.call_args.kwargs["parent_message_id"], DISPATCH)
        self.assertEqual(chase.poll_due(now=NOW)["sent"], 0)
        self.send.assert_called_once()

    def test_no_send_for_every_ineligible_state(self):
        for changes in [dict(status="completed"), dict(status="unknown"), dict(stored_outreach_hold=True),
                        dict(outreach_hold_status="held"), dict(overdue=False), dict(overdue=None),
                        dict(next_due_at=(NOW+timedelta(minutes=1)).isoformat()), dict(next_due_at=None),
                        dict(pending_reply=True), dict(reply_processing=True), dict(pending_reply_count=1),
                        dict(processing_reply_count=1), dict(pending_replies_truncated=True),
                        dict(owner_user_id=999)]:
            with self.subTest(changes=changes):
                self.data = payload()
                self.task().update(changes)
                chase.poll_due(now=NOW)
                self.send.assert_not_called()

    def add_pending_reply(self, **changes):
        reply = dict(id=71, status="pending", group_id=GROUP, dispatch_message_id=DISPATCH,
                     message_id="reply-id", reason_codes=["unsupported_stage", "missing_deadline"])
        reply.update(changes)
        self.task().update(pending_reply=True, pending_reply_count=1, pending_replies=[reply])

    def test_pending_only_requests_one_complete_supplement_in_same_daily_slot(self):
        self.add_pending_reply()
        self.assertEqual(chase.poll_due(now=NOW)["sent"], 1)
        text = self.send.call_args.args[0]
        self.assertIn("已回复", text)
        self.assertIn("线索编号：1；补充回写：71", text)
        self.assertIn("进度", text)
        self.assertIn("截止时间", text)
        self.assertNotIn("私有客户", text)
        self.assertNotIn("下一步：核实联系人", text)
        self.data = payload()
        self.assertEqual(chase.poll_due(now=NOW)["sent"], 0)
        self.send.assert_called_once()

    def test_pending_and_regular_share_a_single_message(self):
        self.data = payload(2)
        self.add_pending_reply()
        self.assertEqual(chase.poll_due(now=NOW)["sent"], 1)
        text = self.send.call_args.args[0]
        self.assertIn("线索 #2", text)
        self.assertIn("补充回写：71", text)
        self.assertEqual(self.send.call_args.kwargs["parent_message_id"], DISPATCH)

    def test_deadline_only_reply_keeps_the_two_references_and_asks_only_for_time(self):
        self.add_pending_reply(reason_codes=["source_deadline_required"])
        self.assertEqual(chase.poll_due(now=NOW)["sent"], 1)
        body = self.send.call_args.args[0]
        self.assertIn("线索编号：1；补充回写：71；截止时间：", body)
        self.assertIn("只补截止时间", body)
        self.assertNotIn("再按实际填写", body)

    def test_unsafe_or_incomplete_supplement_context_does_not_send(self):
        for reply, task in [
            (dict(group_id="wrong"), {}), (dict(dispatch_message_id="wrong"), {}),
            (dict(message_id=None), {}), (dict(status="received"), {}),
            (dict(reason_codes=["source_restricted", "missing_deadline"]), {}),
            ({}, dict(pending_replies_truncated=True)), ({}, dict(reply_processing=True)),
            ({}, dict(stored_outreach_hold=True)), ({}, dict(overdue=False)),
            ({}, dict(status="completed")), ({}, dict(pending_reply_count=2)),
        ]:
            with self.subTest(reply=reply, task=task):
                self.data = payload()
                self.add_pending_reply(**reply)
                self.task().update(task)
                chase.poll_due(now=NOW)
                self.send.assert_not_called()

    def test_environment_disable_hours_and_bad_config_fail_closed(self):
        for attr, value in [("acquisition_chase_enabled", False), ("scheduler_enabled", False),
                            ("environment", "development"), ("remote_db_from_host", True),
                            ("acquisition_chase_targets", "{}"),
                            ("acquisition_supervision_url", "http://gtm.example.test"),
                            ("acquisition_supervision_token", "short")]:
            old = getattr(self.settings, attr)
            setattr(self.settings, attr, value)
            chase.poll_due(now=NOW)
            self.send.assert_not_called()
            setattr(self.settings, attr, old)
        chase.poll_due(now=NOW.replace(hour=20))
        self.send.assert_not_called()

    def test_stale_unknown_environment_pending_owner_and_partial_queue_fail_closed(self):
        variants = []
        for environment in [None, "demo"]:
            item = payload(); item["data"]["environment"] = environment; variants.append(item)
        item = payload(); item["data"]["source_tasks"]["as_of"] = (NOW-timedelta(minutes=6)).isoformat(); variants.append(item)
        item = payload(); item["data"]["source_tasks"]["as_of"] = (NOW+timedelta(minutes=2)).isoformat(); variants.append(item)
        item = payload(); item["data"]["source_tasks"]["total"] = 2; variants.append(item)
        item = payload(); item["data"]["owner_pending_replies"].update(total=1, by_owner=[dict(owner_user_id=4,pending=1,received=0)]); variants.append(item)
        for item in variants:
            self.data = item
            chase.poll_due(now=NOW)
            self.send.assert_not_called()

    def test_incomplete_second_page_does_not_send_first_page(self):
        self.data = payload(100)
        self.data["data"]["source_tasks"].update(total=101, has_more=True)
        chase.poll_due(now=NOW)
        self.send.assert_not_called()

    def test_missing_roster_or_missing_fixed_bot_does_not_send(self):
        self.started[3].return_value = set()
        chase.poll_due(now=NOW)
        self.send.assert_not_called()

    def test_transport_failure_is_redacted_and_not_sent(self):
        self.client.get.side_effect = httpx.ConnectError("secret may appear here")
        result = chase.poll_due(now=NOW)
        self.assertNotIn("secret", str(result))
        self.send.assert_not_called()

    def test_failed_delivery_does_not_claim_success(self):
        self.send.return_value = False
        result = chase.poll_due(now=NOW)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        chase.poll_due(now=NOW)
        self.send.assert_called_once()

    def test_all_pages_required_and_full_count_used(self):
        first = payload(100)
        first["data"]["source_tasks"].update(total=101, has_more=True)
        second = payload()
        second["data"]["source_tasks"].update(total=101, offset=100)
        second["data"]["source_tasks"]["items"][0]["task_id"] = 101
        values = iter([first, second])
        self.client.get.side_effect = lambda *a, **k: httpx.Response(
            200, request=httpx.Request("GET", "https://gtm.example.test"), json=next(values))
        self.assertEqual(chase.poll_due(now=NOW)["eligible_tasks"], 101)
        self.send.assert_called_once()
        self.assertIn("101 条", self.send.call_args.args[0])
        self.assertIn("其余 93 条", self.send.call_args.args[0])

    def test_unmapped_pending_messages_fail_closed(self):
        self.data["data"]["owner_pending_replies"]["total"] = 1
        chase.poll_due(now=NOW)
        self.send.assert_not_called()

    def test_recipient_verification_uses_exact_bot_and_active_member(self):
        target = chase.Target.model_validate(TARGET)
        # Bypass this class's network guard only for the pure mocked directory check.
        self.patches[3].stop()
        self.patches.remove(self.patches[3])
        group = dict(id=GROUP, members=[dict(member_type="user", user_id=101,
                                            employee_name="测试负责人", role="member")])
        bot = dict(app_id="fixed-supervisor", channel_id=GROUP, channel_type="group")
        with patch.dict("os.environ", {"PDCA_DUZHAN_BOT_APP_ID": "fixed-supervisor",
                                        "PDCA_DUZHAN_BOT_APP_SECRET": "test-only"}), \
             patch("app.vertu.client.run_vertu_sync_json") as directory:
            directory.side_effect = [{"channels": [bot]}, {"channels": [group]}]
            self.assertEqual(chase.verified_recipients([target]), {4})
            directory.side_effect = [{"channels": [dict(bot, app_id="other-bot")]}, {"channels": [group]}]
            self.assertEqual(chase.verified_recipients([target]), set())
            directory.side_effect = [{"channels": [bot]}, {"channels": [dict(group, members=[])]}]
            self.assertEqual(chase.verified_recipients([target]), set())


if __name__ == "__main__":
    unittest.main()
