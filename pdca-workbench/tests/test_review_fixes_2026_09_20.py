# -*- coding: utf-8 -*-
"""2026-09-20 审查修复的回归用例（噪声正则 / 幂等键 / 附件名 / claim 重试 / 工时口径）。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.duzhan_ledger import _PERF_NOISE_RE, estimate_hours, parse_performance_buckets


class NoiseRegexTests(unittest.TestCase):
    """审查 P1：正则里的 \\s 曾被写成字面 s，空白容错失效。"""

    def test_whitespace_variants_are_filtered(self):
        for text in ("水单（无）", "水单 （无）", "水单（ 无 ）", "意向 （无）", "无 VPS 留痕", "无VPS留痕",
                     "20:00 [晚追]：无 VPS 留痕记录"):
            self.assertTrue(_PERF_NOISE_RE.search(text), text)

    def test_bucket_parser_drops_template_echo(self):
        msgs = [
            {"sender_user_id": 1, "message_type": "text", "body": "水单 （无）", "created_at": "2026-09-19T02:00:00Z"},
            {"sender_user_id": 1, "message_type": "text", "body": "意向（ 无 ）", "created_at": "2026-09-19T02:01:00Z"},
        ]
        buckets = parse_performance_buckets(msgs, 1)
        self.assertEqual(buckets["slip"], [])
        self.assertEqual(buckets["intent"], [])


class HoursSemanticsTests(unittest.TestCase):
    """审查 P2：零证据时工时是「没出数」而不是「0 小时」。"""

    def test_no_evidence_returns_none(self):
        est = estimate_hours([], {})
        self.assertIsNone(est["minutes"])
        self.assertEqual(est["band"], "待确认")

    def test_real_zero_still_zero(self):
        est = estimate_hours([{"outbound": 0, "inbound": 0, "last": ""}], {"mto_count": 0})
        self.assertIsNotNone(est["minutes"])


class IdempotencyNamespaceTests(unittest.TestCase):
    """审查 P0：Agent 草稿与确定性三追推送不能共用同一个幂等键。"""

    def test_agent_and_duzhan_keys_differ(self):
        from app.duzhan import _idempotency_key

        duzhan_key = _idempotency_key("Asia/Shanghai", "2026-09-20", 20, "chan-1234")
        agent_key = _idempotency_key("Asia/Shanghai", "2026-09-20", 20, "chan-1234", producer="agent")
        self.assertNotEqual(duzhan_key, agent_key)
        self.assertTrue(duzhan_key.startswith("duzhan-"))
        self.assertTrue(agent_key.startswith("agent-"))


class AttachmentNameTests(unittest.TestCase):
    """审查 P2：附件名要净化，防路径穿越。"""

    def test_traversal_is_stripped(self):
        from app.evidence_report import _safe_attachment_name

        cleaned = _safe_attachment_name("..\\..\\evil.png", 3)
        self.assertNotIn("..", cleaned)
        self.assertNotIn("/", cleaned)
        self.assertNotIn("\\", cleaned)
        self.assertTrue(cleaned.endswith("evil.png"))

    def test_download_cleans_temp_dir(self):
        import tempfile
        from pathlib import Path

        from app import evidence_report

        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def fake_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(path)
            return path

        with mock.patch("tempfile.mkdtemp", side_effect=fake_mkdtemp), mock.patch(
            "app.vertu.client.run_vertu_sync", return_value=(1, "", "fail")
        ):
            evidence_report.download_images([{"display": "x"}], {"x": []}, 1)
        self.assertTrue(created)
        for path in created:
            self.assertFalse(Path(path).exists(), "临时目录必须回收")


class ClaimRetryTests(unittest.TestCase):
    """审查 P1：failed 允许兜底触发重试（重复外发由幂等键兜住）。"""

    def test_failed_can_be_reclaimed(self):
        from datetime import datetime, timezone

        from app.models.scheduled_job_run import ScheduledJobRun
        from app.scheduler import run_ledger

        row = ScheduledJobRun(
            run_key="duzhan:test", job_name="duzhan", bucket="test", status="failed",
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def exec(self, _stmt):
                class Result:
                    def first(self_inner):
                        return row

                return Result()

            def add(self, _obj):
                return None

            def commit(self):
                return None

        with mock.patch("app.scheduler.run_ledger.Session", lambda *a, **k: FakeSession()):
            self.assertTrue(run_ledger.claim_run("duzhan", "test"))
        self.assertEqual(row.status, "sending")

    def test_sent_still_blocked(self):
        from datetime import datetime, timezone

        from app.models.scheduled_job_run import ScheduledJobRun
        from app.scheduler import run_ledger

        row = ScheduledJobRun(
            run_key="duzhan:test2", job_name="duzhan", bucket="test2", status="sent",
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def exec(self, _stmt):
                class Result:
                    def first(self_inner):
                        return row

                return Result()

            def add(self, _obj):
                return None

            def commit(self):
                return None

        with mock.patch("app.scheduler.run_ledger.Session", lambda *a, **k: FakeSession()):
            self.assertFalse(run_ledger.claim_run("duzhan", "test2"))


if __name__ == "__main__":
    unittest.main()