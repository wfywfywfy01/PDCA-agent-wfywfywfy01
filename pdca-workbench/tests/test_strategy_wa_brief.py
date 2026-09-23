# -*- coding: utf-8 -*-
"""三策略 WhatsApp HTML：分类、渲染、08:00 调度。不联网。"""
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from app.strategy_wa_brief import (
    OwnerScan,
    Strategy,
    TZ,
    build_html,
    build_im_body,
    classify,
    strategies_for,
    topic_verdict,
    window_for,
    window_text,
)


class ClassifyTests(unittest.TestCase):
    def test_watch_strong(self):
        labels = dict(classify("本单满30万可加提腕表资格"))
        self.assertEqual(labels["watch"], "strong")

    def test_apple_watch_repair_ignored(self):
        labels = dict(classify("欢迎来到 SPR。我们维修 Apple Watch、AirPods"))
        self.assertNotIn("watch", labels)

    def test_clearance_strong(self):
        labels = dict(
            classify("pay 30%, get full- price goods, 70% rest payment by three months.")
        )
        self.assertEqual(labels["clear"], "strong")

    def test_clearance_upfront_q4(self):
        labels = dict(
            classify(
                "the company accepts a 30% upfront payment, with the remaining 70% to be settled in Q4."
            )
        )
        self.assertEqual(labels["clear"], "strong")

    def test_mto_rebate(self):
        labels = dict(classify("BESPOKE MTO +5% rebate within 72 hours"))
        self.assertEqual(labels["mto"], "strong")

    def test_not_meta1_not_watch_strategy(self):
        labels = dict(classify("not meta 1"))
        self.assertEqual(labels, {})


class AgentQPolicyTests(unittest.TestCase):
    """新政策：Agent Q 碳纤维套装全球首发配额（9/30 截止）。"""

    def test_allocation_price_is_strong(self):
        labels = dict(
            classify(
                "Agent Q carbon fibre set, allocation price USD 3,763.20 per set, "
                "deposit to lock your allocation."
            )
        )
        self.assertEqual(labels["agentq"], "strong")

    def test_50_sets_worldwide_is_strong(self):
        labels = dict(classify("全球限量 50 套，仅限海外经销商，定金锁配额"), )
        self.assertEqual(labels["agentq"], "strong")

    def test_deadline_is_strong(self):
        labels = dict(
            classify("Deadline: Sep 30, 2026 24:00 GMT+8. Deposit confirms the allocation.")
        )
        self.assertEqual(labels["agentq"], "strong")

    def test_mention_only_is_weak(self):
        labels = dict(classify("Agent Q 到货了，可以下单"))
        self.assertEqual(labels["agentq"], "weak")

    def test_agent_q_no_longer_counts_as_mto(self):
        labels = dict(classify("Agent Q carbon fibre set, allocation price USD 3,763.20"))
        self.assertNotIn("mto", labels)

    def test_unrelated_text_not_matched(self):
        labels = dict(classify("not meta 1"))
        self.assertNotIn("agentq", labels)


class StrategyExpiryTests(unittest.TestCase):
    """until 到期后不再出现在报告里；老策略没写 until 就一直查。"""

    def _with(self, items):
        return mock.patch(
            "app.strategy_wa_brief.load_strategies", return_value=(items, [])
        )

    def test_until_filters_expired_only(self):
        items = [
            Strategy(id="agentq", label="新政策", strong=[], weak=[], until="2026-09-30"),
            Strategy(id="clear", label="清库", strong=[], weak=[]),
        ]
        with self._with(items):
            self.assertEqual(
                [item.id for item in strategies_for("2026-09-23")], ["agentq", "clear"]
            )
            self.assertEqual(
                [item.id for item in strategies_for("2026-09-30")], ["agentq", "clear"]
            )
            self.assertEqual([item.id for item in strategies_for("2026-10-01")], ["clear"])

    def test_all_expired_produces_no_active_strategies(self):
        items = [Strategy(id="old", label="旧", strong=[], weak=[], until="2026-01-01")]
        with self._with(items):
            self.assertEqual(strategies_for("2026-10-01"), [])

    def test_all_expired_stops_report_before_scanning_messages(self):
        from app.strategy_wa_brief import run_report

        items = [Strategy(id="old", label="旧", strong=[], weak=[], until="2026-01-01")]
        with self._with(items), mock.patch("app.strategy_wa_brief.scan_owners") as scan:
            with self.assertRaisesRegex(RuntimeError, "没有有效策略"):
                run_report("2026-10-01")
        scan.assert_not_called()

    def test_bundled_file_has_agentq_until_sep30(self):
        import json
        from pathlib import Path

        raw = json.loads(
            Path(__file__).resolve().parents[1].joinpath("app/wa_strategies.json").read_text(
                encoding="utf-8"
            )
        )
        entry = next(s for s in raw["strategies"] if s["id"] == "agentq")
        self.assertEqual(entry["until"], "2026-09-30")


class WindowTests(unittest.TestCase):
    def test_24h_before_8am(self):
        start, end = window_for("2026-09-19")
        self.assertEqual(start, datetime(2026, 9, 18, 8, 0, tzinfo=TZ))
        self.assertEqual(end, datetime(2026, 9, 19, 8, 0, tzinfo=TZ))
        self.assertIn("09-18 08:00 → 09-19 08:00", window_text(start, end))


class RenderTests(unittest.TestCase):
    def test_html_and_im_body(self):
        start, end = window_for("2026-09-19")
        scans = [
            OwnerScan("杨晶晶", 47, message_count=2, hits=[]),
            OwnerScan("Lina", 171, message_count=0, wa_configured=False, note="触达 0"),
        ]
        from app.strategy_wa_brief import Hit

        scans[0].hits.append(
            Hit(
                "杨晶晶",
                "clear",
                "strong",
                "2026-09-18 12:00:00",
                "919***4798",
                "outbound",
                "text",
                "pay 30%, get full- price goods",
            )
        )
        html_text = build_html("2026-09-19", start, end, scans)
        self.assertIn("Q4 清库", html_text)
        self.assertIn("pay 30%", html_text)
        self.assertIn("无WA", html_text)
        body = build_im_body("2026-09-19", start, end, scans)
        self.assertIn("①", body)
        self.assertIn("杨晶晶有", body)
        self.assertIn("Lina无WA", body)
        self.assertEqual(topic_verdict(scans[0], "clear"), "有")
        self.assertEqual(topic_verdict(scans[1], "watch"), "无WA")
        empty_incomplete = OwnerScan("杨晶晶", 47, message_count=0, complete=False)
        self.assertEqual(topic_verdict(empty_incomplete, "clear"), "待确认")
        scanned = OwnerScan("Viki", 216, message_count=40, complete=False)
        self.assertEqual(topic_verdict(scanned, "mto"), "无")


class JobRegistrationTests(unittest.TestCase):
    def _register(self, **over: object):
        from app.scheduler import jobs as scheduler_jobs

        class RecordingScheduler:
            def __init__(self):
                self.jobs = []

            def add_job(self, func, *args, **kwargs):
                self.jobs.append((func, args, kwargs))

            def start(self):
                return None

        base = {
            "scheduler_enabled": True,
            "sync_cron": "0 6 * * *",
            "daily_report_enabled": False,
            "todo_remind_enabled": False,
            "todo_remind_times": [],
            "todo_group_notice_enabled": False,
            "todo_group_channel_id": "",
            "todo_scoring_enabled": False,
            "todo_ledger_sync_enabled": False,
            "todo_brief_enabled": False,
            "todo_okr_link_enabled": False,
            "mto_temp_cleanup_enabled": False,
            "daily_digest_enabled": False,
            "evidence_report_enabled": False,
            "strategy_wa_brief_enabled": True,
            "strategy_wa_brief_time": "08:00",
            "campaign_wa_check_enabled": True,
            "campaign_wa_check_time": "08:00",
        }
        base.update(over)
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with mock.patch.object(
                scheduler_jobs, "get_settings", return_value=SimpleNamespace(**base)
            ), mock.patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        return [kwargs["id"] for _, _, kwargs in scheduler.jobs]

    def test_strategy_check_uses_campaign_slot_only(self):
        ids = self._register()
        self.assertIn("campaign_wa_check", ids)
        self.assertNotIn("strategy_wa_brief", ids)

    def test_campaign_slot_can_be_turned_off(self):
        ids = self._register(campaign_wa_check_enabled=False)
        self.assertNotIn("campaign_wa_check", ids)
        self.assertNotIn("strategy_wa_brief", ids)


class RobustnessTests(unittest.TestCase):
    def test_bad_regex_does_not_drop_other_strategies(self):
        import json
        import tempfile
        from pathlib import Path

        from app import strategy_wa_brief as mod

        mod._loaded = None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wa_strategies.json"
            path.write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"id": "bad", "label": "坏", "strong": ["("]},
                            {"id": "ok", "label": "好", "strong": ["圣诞"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(mod, "strategies_path", return_value=path):
                labels = dict(mod.classify("圣诞备货"))
        mod._loaded = None
        self.assertEqual(labels, {"ok": "strong"})

    def test_one_owner_error_keeps_the_rest(self):
        from app.duzhan_ledger import Owner
        from app.strategy_wa_brief import scan_owners

        owners = [
            Owner("g", "于冰", employee_id=45),
            Owner("g", "杨晶晶", employee_id=47),
        ]

        def fetch(employee_id, start, end):
            if employee_id == 45:
                raise RuntimeError("mcp down")
            return [], True, ""

        with mock.patch("app.strategy_wa_brief.OWNERS", owners), mock.patch(
            "app.strategy_wa_brief.fetch_owner_messages", side_effect=fetch
        ), mock.patch(
            "app.strategy_wa_brief.mcp_call", return_value={"summary": "客户 0"}
        ):
            scans = scan_owners(
                datetime(2026, 9, 18, 8, tzinfo=TZ),
                datetime(2026, 9, 19, 8, tzinfo=TZ),
            )
        self.assertEqual([item.display for item in scans], ["于冰", "杨晶晶"])
        self.assertIn("采集失败", scans[0].note)
        self.assertEqual(topic_verdict(scans[0], "mto"), "待确认")
        self.assertEqual(topic_verdict(scans[1], "mto"), "无WA")


class SendAttachTests(unittest.TestCase):
    def test_dry_run_skips_send(self):
        from app import strategy_wa_brief as mod

        fake = OwnerScan("于冰", 45, message_count=0, complete=True)
        with mock.patch.object(mod, "scan_owners", return_value=[fake]), mock.patch.object(
            mod, "save_html", return_value=__import__("pathlib").Path("x.html")
        ), mock.patch("app.todos.service.send_direct_message") as send:
            result = mod.run_brief("2026-09-19", dry_run=True)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "dry_run")
        send.assert_not_called()
