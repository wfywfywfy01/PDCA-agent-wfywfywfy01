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
    def test_removed_watch_strategy_no_longer_matches(self):
        """2026-09-24 老板要求：机械腕表配给策略已删，不应再判分。"""
        labels = dict(classify("本单满30万可加提腕表资格"))
        self.assertNotIn("watch", labels)

    def test_apple_watch_repair_ignored(self):
        labels = dict(classify("欢迎来到 SPR。我们维修 Apple Watch、AirPods"))
        self.assertNotIn("watch", labels)

    def test_removed_clearance_strategy_no_longer_matches(self):
        """2026-09-24 老板要求：Q4 清库策略已删，相关话术不再判分。"""
        self.assertNotIn(
            "clear",
            dict(classify("pay 30%, get full- price goods, 70% rest payment by three months.")),
        )
        self.assertNotIn(
            "clear",
            dict(
                classify(
                    "the company accepts a 30% upfront payment, with the remaining 70% to be settled in Q4."
                )
            ),
        )

    def test_smart_jewelry_discount_is_strong(self):
        """2026-09-24 新政策：智能珠宝（METAWATCH H1/S1、AI RING、Crystal RING），至 9/30。"""
        labels = dict(classify("METAWATCH S1 拿货 5 折，单台利润 15,015，9月25日截止"))
        self.assertEqual(labels["smartjewel"], "strong")

    def test_smart_jewelry_order_gift_is_strong(self):
        labels = dict(classify("一代一次提 30 台赠 3 台，二代 20 万元赠 1 台，可提前锁定第三代 5 台认购权"))
        self.assertEqual(labels["smartjewel"], "strong")

    def test_smart_jewelry_theme_coverage(self):
        """2026-09-24：话术后 5 点做语义匹配，五个要点都要能命中。"""
        from app.strategy_wa_brief import _strategy_by_id, theme_hits

        strategy = _strategy_by_id("smartjewel")
        text = (
            "H1: 40% of the retail price (60% off); buy 30 units, get 3 free. "
            "Your order secures advance purchase rights for 5 Gen 3 smartwatches. "
            "Website prices remain unchanged. Order by September 25."
        )
        self.assertEqual(
            sorted(theme_hits(strategy, text)), ["deadline", "gen3", "gift", "price", "stable"]
        )

    def test_smart_jewelry_semantic_verdict_needs_two_points(self):
        """讲清 ≥2 个重点算「有」，只讲 1 个算「部分」。"""
        from app.strategy_wa_brief import OwnerScan, topic_verdict

        scan = OwnerScan(display="测试", employee_id=1, message_count=10)
        scan.theme_ids["smartjewel"] = {"price"}
        self.assertEqual(topic_verdict(scan, "smartjewel"), "部分")
        scan.theme_ids["smartjewel"] = {"price", "deadline"}
        self.assertEqual(topic_verdict(scan, "smartjewel"), "有")

    def test_vps_im_messages_are_scanned(self):
        """2026-09-24 老板：不只查 WhatsApp，VPS IM（达标群/跟进群）本人的发言也要算。"""
        from app.duzhan_ledger import Owner
        from app.strategy_wa_brief import fetch_owner_im_messages, im_channels

        owner = Owner(
            "新人小组业绩达标群",
            "邓琳莹",
            im_user_id=14247,
            follow_channel_id="chan-follow",
        )
        labels = [label for label, _cid in im_channels(owner)]
        self.assertIn("客户跟进群", labels)
        messages = [
            {
                "id": "m1",
                "sender_user_id": 14247,
                "created_at": "2026-09-24T09:30:00Z",
                "body": "METAWATCH S1 拿货 5 折，单笔利润 15,015，9月25日截止",
                "message_type": "text",
            },
            {
                "id": "m2",
                "sender_user_id": 999,
                "created_at": "2026-09-24T09:31:00Z",
                "body": "别人说的话",
                "message_type": "text",
            },
        ]
        def fake_history(channel_id, date_from, limit=100):
            # 目标群与跟进群各返回一次，验证只算本人发言、且两个会话都会扫
            return messages if channel_id == "chan-follow" else []

        with mock.patch("app.strategy_wa_brief._im_history", side_effect=fake_history):
            rows = fetch_owner_im_messages(
                owner,
                datetime(2026, 9, 24, 8, tzinfo=TZ),
                datetime(2026, 9, 25, 8, tzinfo=TZ),
            )
        self.assertEqual(len(rows), 1, "只算本人发言")
        self.assertEqual(rows[0]["_platform"], "VPS IM")
        self.assertIn("5 折", rows[0]["content"])

    def test_window_im_records_filter_by_sender_and_window(self):
        """2026-09-24 老板：VPS 聊天用 vps-work 全域记录拿，只留核查对象本人。"""
        from app.duzhan_ledger import Owner
        from app.strategy_wa_brief import fetch_window_im_messages

        owners = [Owner("新人小组业绩达标群", "邓琳莹", im_user_id=14247)]
        page = {
            "messages": [
                {
                    "id": "m1",
                    "sender_user_id": 14247,
                    "created_at": "2026-09-24T09:00:00Z",
                    "body": "METAWATCH S1 拿货 5 折，9月25日截止",
                    "message_type": "text",
                    "channel": {"id": "c1", "name": "客户跟进群", "type": "group"},
                },
                {
                    "id": "m2",
                    "sender_user_id": 999,
                    "created_at": "2026-09-24T09:01:00Z",
                    "body": "别人的发言",
                    "message_type": "text",
                    "channel": {"id": "c1", "name": "客户跟进群", "type": "group"},
                },
                {
                    "id": "m3",
                    "sender_user_id": 14247,
                    "created_at": "2026-09-20T09:00:00Z",
                    "body": "窗口外的旧消息",
                    "message_type": "text",
                    "channel": {"id": "c2", "name": "私聊", "type": "direct"},
                },
            ],
            "pagination": {"has_next": False},
        }
        with mock.patch("app.strategy_wa_brief._im_records_page", return_value=page):
            got, complete = fetch_window_im_messages(
                datetime(2026, 9, 24, 8, tzinfo=TZ),
                datetime(2026, 9, 25, 8, tzinfo=TZ),
                owners,
            )
        self.assertEqual(list(got), ["邓琳莹"])
        self.assertEqual(len(got["邓琳莹"]), 1, "只留本人 + 窗口内")
        self.assertEqual(got["邓琳莹"][0]["_platform"], "VPS IM")
        self.assertEqual(got["邓琳莹"][0]["customer_display"], "客户跟进群")
        self.assertTrue(complete, "首页有数据 → 视为完整")

    def test_window_im_mid_pagination_failure_marks_incomplete(self):
        """中途某页拿不到 → 标不完整（不静默当作扫完）。"""
        from app.duzhan_ledger import Owner
        from app.strategy_wa_brief import fetch_window_im_messages

        owners = [Owner("新人小组业绩达标群", "邓琳莹", im_user_id=14247)]
        first = {
            "messages": [
                {
                    "id": "m1",
                    "sender_user_id": 14247,
                    "created_at": "2026-09-24T09:00:00Z",
                    "body": "METAWATCH S1 5 折",
                    "message_type": "text",
                    "channel": {"id": "c1", "name": "客户跟进群", "type": "group"},
                }
            ],
            "pagination": {"has_next": True},
        }
        with mock.patch(
            "app.strategy_wa_brief._im_records_page", side_effect=[first, {}, {}]
        ), mock.patch("app.strategy_wa_brief.time.sleep"):
            got, complete = fetch_window_im_messages(
                datetime(2026, 9, 24, 8, tzinfo=TZ),
                datetime(2026, 9, 25, 8, tzinfo=TZ),
                owners,
            )
        self.assertEqual(len(got["邓琳莹"]), 1)
        self.assertFalse(complete, "中途断页必须标不完整")

    def test_new_group_added_to_targets(self):
        """老板 2026-09-24：策略核查对象加入新人组（江旭即 Sana）。"""
        from app.strategy_wa_brief import TARGETS

        for name in ("邓琳莹", "Safae", "王宇彤", "张月馨", "江旭"):
            self.assertIn(name, TARGETS)

    def test_smart_jewelry_english_policy_is_strong(self):
        """2026-09-24 实测漏判：英文版政策（40% of retail price / buy 30 get 3 free）必须算「有」。"""
        labels = dict(
            classify(
                "H1 Smart Watch: Available at 40% of the retail price (60% off); buy 30 units, "
                "get 3 free - limited to 200 pieces. S1: 50% of the retail price; order worth "
                "RMB 200,000 and get 1 free. Lock in 5 units of the third-generation watch "
                "launching in November."
            )
        )
        self.assertEqual(labels["smartjewel"], "strong")

    def test_smart_jewelry_ring_mention_only_is_weak(self):
        labels = dict(classify("AI RING 到货了，有兴趣的看看"))
        self.assertEqual(labels["smartjewel"], "weak")

    def test_smart_jewelry_apple_watch_noise_ignored(self):
        labels = dict(classify("Apple Watch 维修可以找他"))
        self.assertNotIn("smartjewel", labels)

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

    def test_bundled_file_has_smart_jewelry_until_sep30(self):
        import json
        from pathlib import Path

        raw = json.loads(
            Path(__file__).resolve().parents[1].joinpath("app/wa_strategies.json").read_text(
                encoding="utf-8"
            )
        )
        ids = [s["id"] for s in raw["strategies"]]
        self.assertEqual(ids, ["agentq", "mto", "smartjewel"], "9/24 起只剩这三条")
        entry = next(s for s in raw["strategies"] if s["id"] == "smartjewel")
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
                "agentq",
                "strong",
                "2026-09-18 12:00:00",
                "919***4798",
                "outbound",
                "text",
                "Agent Q 碳纤维套装，配额价 USD 3,763.20，定金锁配额",
            )
        )
        html_text = build_html("2026-09-19", start, end, scans)
        self.assertIn("Agent Q", html_text)
        self.assertIn("3,763.20", html_text)
        self.assertIn("无WA", html_text)
        body = build_im_body("2026-09-19", start, end, scans)
        self.assertIn("①", body)
        self.assertIn("杨晶晶有", body)
        self.assertIn("Lina无WA", body)
        self.assertEqual(topic_verdict(scans[0], "agentq"), "有")
        self.assertEqual(topic_verdict(scans[1], "mto"), "无WA")
        empty_incomplete = OwnerScan("杨晶晶", 47, message_count=0, complete=False)
        self.assertEqual(topic_verdict(empty_incomplete, "agentq"), "待确认")
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
