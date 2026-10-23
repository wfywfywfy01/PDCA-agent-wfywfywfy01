# -*- coding: utf-8 -*-
"""小黑屋管理员派单、提醒与提交证据核对。"""
from __future__ import annotations

import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app import heiwu_tasks
from app.models.pdca_task import PdcaTask


def _members() -> list[dict]:
    return [
        {"member_type": "user", "user_id": 100, "employee_name": "管理员"},
        {"member_type": "user", "user_id": 101, "employee_name": "销售甲"},
        {"member_type": "user", "user_id": 102, "employee_name": "销售乙"},
        {"member_type": "bot", "bot_id": "bot-1", "bot_name": "机器人"},
        {"member_type": "user", "user_id": 103, "employee_name": "已退群", "removed_at": "2026-10-01T00:00:00Z"},
        {"member_type": "user", "user_id": 104, "employee_name": "旁观管理员", "role": "admin"},
        {"member_type": "user", "user_id": 105, "employee_name": "支持同事", "role": "member", "job_title": "数据分析"},
    ]


class AssignmentParsingTests(unittest.TestCase):
    def test_collective_notice_expands_active_users_except_publisher(self):
        message = {
            "id": "notice-1",
            "sender_type": "user",
            "sender_user_id": 100,
            "created_at": "2026-10-12T23:00:00Z",
            "message_type": "text",
            "body": "10月13-15日产品卖点视频作业，请大家完成并提交群内 @所有人",
            "attachments": [],
        }

        tasks = heiwu_tasks.parse_assignment_message(
            message,
            _members(),
            publisher_user_id=100,
        )

        self.assertEqual({task["owner"] for task in tasks}, {"销售甲", "销售乙"})
        self.assertEqual({task["owner_user_id"] for task in tasks}, {"101", "102"})
        self.assertTrue(all(task["title"] == "产品卖点视频作业" for task in tasks))
        self.assertTrue(all(task["start_date"] == "2026-10-13" for task in tasks))
        self.assertTrue(all(task["due_at"] == datetime(2026, 10, 15, 15, 59, 59, tzinfo=timezone.utc) for task in tasks))
        self.assertTrue(all(task["source_message_id"] == "notice-1" for task in tasks))

    def test_named_items_keep_each_owner_and_long_term_deadline(self):
        message = {
            "id": "notice-2",
            "sender_type": "user",
            "sender_user_id": 100,
            "created_at": "2026-10-23T01:00:00Z",
            "message_type": "text",
            "body": "【销售甲】\n1. 今天完成客户回访\n销售乙：长期跟进库存清理",
        }

        tasks = heiwu_tasks.parse_assignment_message(
            message,
            _members(),
            publisher_user_id=100,
        )

        by_owner = {task["owner"]: task for task in tasks}
        self.assertEqual(set(by_owner), {"销售甲", "销售乙"})
        self.assertEqual(by_owner["销售甲"]["title"], "今天完成客户回访")
        self.assertEqual(by_owner["销售甲"]["due_at"], datetime(2026, 10, 23, 15, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(by_owner["销售乙"]["title"], "长期跟进库存清理")
        self.assertIsNone(by_owner["销售乙"]["due_at"])

    def test_reward_notice_and_invalid_date_fail_closed(self):
        base = {
            "id": "notice-noise", "sender_type": "user", "sender_user_id": 100,
            "created_at": "2026-10-23T01:00:00Z", "message_type": "text",
        }
        reward = dict(base, body="@所有人 奖励规则：完成任务并提交作业者可领取奖励")
        invalid = dict(base, id="notice-invalid", body="@所有人 10月32日完成任务并提交")
        self.assertEqual(
            heiwu_tasks.parse_assignment_message(reward, _members(), publisher_user_id=100), []
        )
        self.assertEqual(
            heiwu_tasks.parse_assignment_message(invalid, _members(), publisher_user_id=100), []
        )

    def test_explicit_late_deadline_and_daily_task_are_preserved(self):
        late = {
            "id": "notice-late", "sender_type": "user", "sender_user_id": 100,
            "created_at": "2026-10-23T01:00:00Z", "message_type": "text",
            "body": "@所有人 10月23日23:59前完成产品视频作业并提交",
        }
        daily = dict(
            late,
            id="notice-daily",
            body="@所有人 每天完成客户复盘并提交群内",
        )

        late_tasks = heiwu_tasks.parse_assignment_message(late, _members(), publisher_user_id=100)
        daily_tasks = heiwu_tasks.parse_assignment_message(daily, _members(), publisher_user_id=100)

        self.assertTrue(late_tasks)
        self.assertTrue(all(task["due_at"] == datetime(2026, 10, 23, 15, 59, tzinfo=timezone.utc) for task in late_tasks))
        self.assertTrue(daily_tasks)
        self.assertTrue(all(task["recurring_daily"] for task in daily_tasks))

    def test_date_only_deadline_is_not_overdue_at_evening_check(self):
        message = {
            "id": "notice-end-of-day", "sender_type": "user", "sender_user_id": 100,
            "created_at": "2026-10-23T01:00:00Z", "message_type": "text",
            "body": "@所有人 10月23日完成产品视频作业并提交",
        }
        task = heiwu_tasks.parse_assignment_message(
            message, _members(), publisher_user_id=100
        )[0]

        result = heiwu_tasks.evaluate_task_evidence(
            task, [], history_complete=True,
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(result["state"], "progress")


class AssignmentPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "heiwu.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch("app.database.get_engine", return_value=self.engine)
        self.engine_patch.start()

    def tearDown(self):
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _rows(self) -> list[PdcaTask]:
        with Session(self.engine) as session:
            return list(session.exec(select(PdcaTask).order_by(PdcaTask.id)).all())

    def _notice(self, body: str, **changes) -> dict:
        row = {
            "id": "notice-persist",
            "sender_type": "user",
            "sender_user_id": 100,
            "created_at": "2026-10-23T01:00:00Z",
            "updated_at": "2026-10-23T01:00:00Z",
            "message_type": "text",
            "body": body,
        }
        row.update(changes)
        return row

    def test_repeat_is_idempotent_and_edit_reassigns_without_duplicate(self):
        collective = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        first = heiwu_tasks.sync_assignment_messages(
            [collective], _members(), channel_id="group-1", publisher_user_id=100
        )
        second = heiwu_tasks.sync_assignment_messages(
            [collective], _members(), channel_id="group-1", publisher_user_id=100
        )
        self.assertEqual(first["created"], 2)
        self.assertEqual(second, {"created": 0, "updated": 0, "cancelled": 0, "ignored": 0})
        self.assertEqual(len(self._rows()), 2)

        edited = self._notice(
            "销售甲：今天完成异议处理话术",
            updated_at="2026-10-23T02:00:00Z",
        )
        changed = heiwu_tasks.sync_assignment_messages(
            [edited], _members(), channel_id="group-1", publisher_user_id=100
        )
        self.assertEqual(changed, {"created": 0, "updated": 1, "cancelled": 1, "ignored": 0})
        rows = self._rows()
        current = next(row for row in rows if row.owner == "销售甲")
        removed = next(row for row in rows if row.owner == "销售乙")
        self.assertEqual(current.title, "今天完成异议处理话术")
        self.assertEqual(current.status, "pending")
        self.assertEqual(removed.status, "complete")
        self.assertEqual(removed.verification_status, "rejected")

    def test_withdrawn_notice_closes_all_derived_tasks(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        notice["message_type"] = "recall"
        notice["revoked_at"] = "2026-10-23T03:00:00Z"
        result = heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        self.assertEqual(result["cancelled"], 2)
        self.assertTrue(all(row.status == "complete" for row in self._rows()))
        evidence = json.loads(self._rows()[0].evidence_json)
        self.assertEqual(evidence[-1]["evidence_type"], "source_withdrawal")

    def test_same_task_reposted_with_new_message_id_is_not_duplicated(self):
        first = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        repeated = dict(first, id="notice-repeated", created_at="2026-10-23T02:00:00Z")
        heiwu_tasks.sync_assignment_messages(
            [first, repeated], _members(), channel_id="group-1", publisher_user_id=100
        )
        self.assertEqual(len(self._rows()), 2)

    def test_resync_preserves_existing_delivery_evidence_and_status(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        with Session(self.engine) as session:
            row = session.exec(select(PdcaTask).where(PdcaTask.owner == "销售甲")).one()
            evidence = json.loads(row.evidence_json)
            evidence.append({"evidence_type": "im_message", "message_id": "video-1"})
            row.evidence_json = json.dumps(evidence, ensure_ascii=False)
            row.status = "evidence_submitted"
            row.verification_status = "partial"
            session.add(row)
            session.commit()

        result = heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )

        self.assertEqual(result["updated"], 0)
        row = next(item for item in self._rows() if item.owner == "销售甲")
        self.assertEqual(row.status, "evidence_submitted")
        self.assertTrue(any(item.get("message_id") == "video-1" for item in json.loads(row.evidence_json)))


class EvidenceDecisionTests(unittest.TestCase):
    def _task(self, **changes) -> dict:
        task = {
            "owner": "销售甲",
            "owner_user_id": "101",
            "title": "10月20-22日线上平台视频引流作业，请大家提交群内",
            "start_date": "2026-10-20",
            "due_at": datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
            "source_message_id": "notice-3",
        }
        task.update(changes)
        return task

    def test_date_only_caption_and_video_stays_pending_without_task_content(self):
        messages = [
            {
                "id": "caption-1",
                "sender_user_id": 101,
                "created_at": "2026-10-21T11:55:00Z",
                "message_type": "text",
                "body": "10.20-10.23 作业",
                "attachments": [],
            },
            {
                "id": "video-1",
                "sender_user_id": 101,
                "created_at": "2026-10-21T12:00:00Z",
                "message_type": "video",
                "body": "",
                "attachments": [{"attachment_type": "video", "url": "/private/video"}],
            },
        ]
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(),
            messages,
            history_complete=True,
            now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "pending")

    def test_matching_caption_and_readable_video_count_as_submitted(self):
        messages = [
            {
                "id": "caption-2", "sender_user_id": 101,
                "created_at": "2026-10-21T11:55:00Z", "message_type": "text",
                "body": "线上平台视频引流作业", "attachments": [],
            },
            {
                "id": "video-2", "sender_user_id": 101,
                "created_at": "2026-10-21T12:00:00Z", "message_type": "video",
                "body": "", "attachments": [{"attachment_type": "video", "url": "/private/video"}],
            },
        ]
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(), messages, history_complete=True,
            now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(result["message_ids"], ["video-2"])

    def test_revoked_video_wrong_media_type_and_empty_url_do_not_close_video_task(self):
        variants = [
            {
                "id": "revoked", "sender_user_id": 101,
                "created_at": "2026-10-22T11:00:00Z", "message_type": "video",
                "body": "线上平台视频引流作业", "revoked_at": "2026-10-22T11:30:00Z",
                "attachments": [{"attachment_type": "video", "url": "/v"}],
            },
            {
                "id": "image", "sender_user_id": 101,
                "created_at": "2026-10-22T11:00:00Z", "message_type": "image",
                "body": "线上平台视频引流作业",
                "attachments": [{"attachment_type": "image", "url": "/i"}],
            },
            {
                "id": "empty", "sender_user_id": 101,
                "created_at": "2026-10-22T11:00:00Z", "message_type": "video",
                "body": "线上平台视频引流作业",
                "attachments": [{"attachment_type": "video", "url": ""}],
            },
        ]
        states = [
            heiwu_tasks.evaluate_task_evidence(
                self._task(), [message], history_complete=True,
                now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
            )["state"]
            for message in variants
        ]
        self.assertEqual(states, ["missing", "pending", "pending"])

    def test_text_only_claim_is_pending_not_submission_or_missing(self):
        messages = [{
            "id": "claim-1",
            "sender_user_id": 101,
            "created_at": "2026-10-22T11:00:00Z",
            "message_type": "text",
            "body": "已交，线上平台视频引流作业",
            "attachments": [],
        }]
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(), messages, history_complete=True,
            now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "pending")

    def test_incomplete_history_and_unreadable_or_unsupported_media_are_pending(self):
        due = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        incomplete = heiwu_tasks.evaluate_task_evidence(
            self._task(), [], history_complete=False, now=due
        )
        self.assertEqual(incomplete["state"], "pending")

        unreadable = [{
            "id": "image-1", "sender_user_id": 101,
            "created_at": "2026-10-22T11:00:00Z", "message_type": "image",
            "body": "", "metadata": {"ocr_status": "unreadable"},
            "attachments": [{"attachment_type": "image", "url": "/private/image"}],
            "parent_message_id": "notice-3",
        }]
        self.assertEqual(
            heiwu_tasks.evaluate_task_evidence(
                self._task(), unreadable, history_complete=True, now=due
            )["state"],
            "pending",
        )

        unsupported = [{
            "id": "file-1", "sender_user_id": 101,
            "created_at": "2026-10-22T11:00:00Z", "message_type": "file",
            "body": "",
            "attachments": [{"attachment_type": "file", "name": "work.bin"}],
        }]
        self.assertEqual(
            heiwu_tasks.evaluate_task_evidence(
                self._task(), unsupported, history_complete=True, now=due
            )["state"],
            "pending",
        )

    def test_quoted_media_is_pending_instead_of_submission_or_missing(self):
        quoted = [{
            "id": "quote-1", "sender_user_id": 101,
            "created_at": "2026-10-22T11:00:00Z", "message_type": "text",
            "body": "",
            "attachments": [],
            "quote_snapshot": {
                "message_type": "image",
                "attachment": {"attachment_type": "image", "url": "/quoted/image"},
            },
        }]
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(), quoted, history_complete=True,
            now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "pending")

    def test_not_yet_due_is_progress_instead_of_missing(self):
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(), [], history_complete=True,
            now=datetime(2026, 10, 21, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "progress")

    def test_history_window_before_task_start_is_required_for_missing(self):
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(), [], history_complete=True,
            history_start=datetime(2026, 10, 21, 0, tzinfo=timezone.utc),
            now=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "pending")

    def test_explicit_late_deadline_is_still_in_progress_at_evening_round(self):
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(due_at=datetime(2026, 10, 23, 15, 59, tzinfo=timezone.utc)),
            [], history_complete=True,
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "progress")

    def test_daily_recurring_task_requires_manual_handling(self):
        result = heiwu_tasks.evaluate_task_evidence(
            self._task(recurring_daily=True, due_at=None),
            [], history_complete=True,
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["state"], "pending")


class EvidencePersistenceTests(AssignmentPersistenceTests):
    def test_reconcile_persists_submission_and_keeps_claim_pending(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        messages = [
            {
                "id": "caption", "sender_user_id": 101,
                "created_at": "2026-10-23T11:50:00Z", "message_type": "text",
                "body": "产品卖点视频作业", "attachments": [],
            },
            {
                "id": "video", "sender_user_id": 101,
                "created_at": "2026-10-23T11:55:00Z", "message_type": "video",
                "body": "", "attachments": [{"attachment_type": "video", "url": "/v"}],
            },
            {
                "id": "claim", "sender_user_id": 102,
                "created_at": "2026-10-23T11:55:00Z", "message_type": "text",
                "body": "已交产品卖点视频作业", "attachments": [],
            },
        ]

        result = heiwu_tasks.reconcile_task_evidence(
            messages,
            channel_id="group-1",
            history_complete=True,
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )

        self.assertEqual({item["owner"] for item in result["submitted"]}, {"销售甲"})
        self.assertEqual({item["owner"] for item in result["pending"]}, {"销售乙"})
        by_owner = {row.owner: row for row in self._rows()}
        self.assertEqual(by_owner["销售甲"].status, "evidence_submitted")
        self.assertEqual(by_owner["销售甲"].verification_status, "partial")
        self.assertEqual(by_owner["销售乙"].status, "pending")
        self.assertEqual(by_owner["销售乙"].verification_status, "pending_manual")
        self.assertIn("只有提交说明", by_owner["销售乙"].blocked_reason)

    def test_revoked_delivery_reopens_previously_submitted_task(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        evidence = [
            {"id": "caption", "sender_user_id": 101, "created_at": "2026-10-23T11:50:00Z",
             "message_type": "text", "body": "产品卖点视频作业", "attachments": []},
            {"id": "video", "sender_user_id": 101, "created_at": "2026-10-23T11:55:00Z",
             "message_type": "video", "body": "",
             "attachments": [{"attachment_type": "video", "url": "/v"}]},
        ]
        heiwu_tasks.reconcile_task_evidence(
            evidence, channel_id="group-1", history_complete=True,
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )
        evidence[1]["revoked_at"] = "2026-10-23T12:05:00Z"

        result = heiwu_tasks.reconcile_task_evidence(
            evidence, channel_id="group-1", history_complete=True,
            now=datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc),
        )

        self.assertIn("销售甲", {item["owner"] for item in result["missing"]})
        row = next(item for item in self._rows() if item.owner == "销售甲")
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.verification_status, "unverified")
        self.assertFalse(any(item.get("message_id") == "video" for item in json.loads(row.evidence_json)))

    def test_edited_delivery_context_reopens_previously_submitted_task(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        heiwu_tasks.sync_assignment_messages(
            [notice], _members(), channel_id="group-1", publisher_user_id=100
        )
        evidence = [{
            "id": "video-edit", "sender_user_id": 101,
            "created_at": "2026-10-23T11:55:00Z", "message_type": "video",
            "body": "产品卖点视频作业",
            "attachments": [{"attachment_type": "video", "url": "/v"}],
        }]
        heiwu_tasks.reconcile_task_evidence(
            evidence, channel_id="group-1", history_complete=True,
            history_start=datetime(2026, 10, 22, 0, tzinfo=timezone.utc),
            now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
        )
        evidence[0]["body"] = "与本任务无关的内容"
        evidence[0]["updated_at"] = "2026-10-23T12:10:00Z"

        result = heiwu_tasks.reconcile_task_evidence(
            evidence, channel_id="group-1", history_complete=True,
            history_start=datetime(2026, 10, 22, 0, tzinfo=timezone.utc),
            now=datetime(2026, 10, 23, 16, tzinfo=timezone.utc),
        )

        self.assertIn("销售甲", {item["owner"] for item in result["missing"]})
        row = next(item for item in self._rows() if item.owner == "销售甲")
        self.assertEqual(row.status, "pending")
        self.assertFalse(any(item.get("message_id") == "video-edit" for item in json.loads(row.evidence_json)))


class SourceFetchTests(unittest.TestCase):
    def test_history_paginates_instead_of_failing_at_200_messages(self):
        first = [{"id": f"m-{index}"} for index in range(200)]
        second = [{"id": f"m-{index}"} for index in range(200, 203)]
        with patch(
            "app.vertu.client.run_vertu_sync_json",
            side_effect=[{"ok": True, "messages": first}, {"ok": True, "messages": second}],
        ) as cli:
            result = heiwu_tasks.fetch_group_history(
                "group-1",
                now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
                lookback_days=21,
            )

        self.assertTrue(result["complete"])
        self.assertEqual(len(result["messages"]), 203)
        self.assertNotIn("--offset", cli.call_args_list[0].args[0])
        second_args = cli.call_args_list[1].args[0]
        self.assertEqual(second_args[second_args.index("--offset") + 1], "200")


class RunRoundTests(AssignmentPersistenceTests):
    def _settings(self):
        return SimpleNamespace(
            heiwu_tasks_enabled=True,
            heiwu_task_publisher_user_ids=(100,),
            heiwu_task_lookback_days=21,
        )

    def _history(self):
        notice = self._notice("今天产品卖点视频作业，请大家完成并提交群内")
        return [
            notice,
            {
                "id": "caption", "sender_user_id": 101,
                "created_at": "2026-10-23T11:50:00Z", "message_type": "text",
                "body": "产品卖点视频作业", "attachments": [],
            },
            {
                "id": "video", "sender_user_id": 101,
                "created_at": "2026-10-23T11:55:00Z", "message_type": "video",
                "body": "", "attachments": [{"attachment_type": "video", "url": "/v"}],
            },
        ]

    def test_manual_pending_is_only_included_in_morning_reminders(self):
        task = {
            "id": 1,
            "owner": "销售甲",
            "owner_user_id": "101",
            "title": "每天提交复盘",
            "start_date": "2026-10-23",
            "due_at": None,
            "last_reminded_at": None,
            "last_reminded_round": "",
        }
        decisions = {"submitted": [], "missing": [], "pending": [task], "progress": []}
        current = datetime(2026, 10, 23, 2, tzinfo=timezone.utc)

        morning = heiwu_tasks._round_groups(
            decisions, round_name="morning", current=current, tz=heiwu_tasks.LOCAL_TZ
        )
        evening = heiwu_tasks._round_groups(
            decisions, round_name="evening", current=current, tz=heiwu_tasks.LOCAL_TZ
        )

        self.assertEqual(len(morning), 1)
        self.assertEqual(evening, [])

    def test_evening_sends_only_missing_owner_and_marks_after_success(self):
        with patch("app.config.get_settings", return_value=self._settings()), \
             patch("app.heiwu.channel_id", return_value="group-1"), \
             patch.object(heiwu_tasks, "fetch_group_history", return_value={
                 "messages": self._history(), "complete": True, "error": ""}), \
             patch.object(heiwu_tasks, "fetch_group_members", return_value={
                 "members": _members(), "complete": True, "error": ""}), \
             patch("app.scheduler.run_ledger.claim_run", return_value=True), \
             patch("app.scheduler.run_ledger.finish_run") as finish, \
             patch("app.heiwu.configured", return_value=True), \
             patch("app.heiwu._reply", return_value=True) as reply:
            result = heiwu_tasks.run_round(
                "evening", now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
            )

        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["reminded"], 1)
        self.assertEqual(reply.call_count, 1)
        self.assertIn("销售乙", reply.call_args.args[0])
        self.assertNotIn("销售甲", reply.call_args.args[0])
        by_owner = {row.owner: row for row in self._rows()}
        self.assertIsNone(by_owner["销售甲"].last_reminded_at)
        self.assertIsNotNone(by_owner["销售乙"].last_reminded_at)
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[2], "sent")

    def test_send_failure_does_not_mark_reminded(self):
        messages = [self._notice("今天产品卖点视频作业，请大家完成并提交群内")]
        with patch("app.config.get_settings", return_value=self._settings()), \
             patch("app.heiwu.channel_id", return_value="group-1"), \
             patch.object(heiwu_tasks, "fetch_group_history", return_value={
                 "messages": messages, "complete": True, "error": ""}), \
             patch.object(heiwu_tasks, "fetch_group_members", return_value={
                 "members": _members(), "complete": True, "error": ""}), \
             patch("app.scheduler.run_ledger.claim_run", return_value=True), \
             patch("app.scheduler.run_ledger.finish_run") as finish, \
             patch("app.heiwu.configured", return_value=True), \
             patch("app.heiwu._reply", return_value=False):
            result = heiwu_tasks.run_round(
                "evening", now=datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
            )
        self.assertEqual(result["reminded"], 0)
        self.assertTrue(result["failed"])
        self.assertTrue(all(row.last_reminded_at is None for row in self._rows()))
        self.assertEqual(finish.call_args.args[2], "failed")


if __name__ == "__main__":
    unittest.main()
