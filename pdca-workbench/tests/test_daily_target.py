# -*- coding: utf-8 -*-
"""滚动日目标（月目标÷当月天数）+ 业绩三关键词（到账/水单/意向）测试。"""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.duzhan import TZ_SHANGHAI, groups_for_tz, render_brief
from app.duzhan_ledger import (
    _perf_amount,
    daily_target_progress,
    daily_target_text,
    parse_performance_buckets,
)


class DailyTargetTests(unittest.TestCase):
    def test_rolling_target_math(self):
        progress = daily_target_progress(200, 147.4, "2026-09-18")
        self.assertEqual(progress["days_in_month"], 30)
        self.assertEqual(progress["days_elapsed"], 18)
        self.assertAlmostEqual(progress["daily_target"], 6.67, places=2)
        self.assertAlmostEqual(progress["rolling_target"], 120.1, places=1)
        self.assertAlmostEqual(progress["gap"], 27.3, places=1)
        self.assertTrue(progress["ahead"])

    def test_rolling_target_behind(self):
        progress = daily_target_progress(300, 80, "2026-09-10")
        self.assertEqual(progress["days_elapsed"], 10)
        self.assertAlmostEqual(progress["rolling_target"], 100.0, places=1)
        self.assertFalse(progress["ahead"])
        self.assertAlmostEqual(progress["gap"], -20.0, places=1)

    def test_missing_target_is_pending_not_zero(self):
        progress = daily_target_progress(None, 50, "2026-09-18")
        self.assertIsNone(progress["daily_target"])
        self.assertIsNone(progress["rolling_target"])
        self.assertEqual(daily_target_text(progress), "待确认")
        self.assertEqual(daily_target_text(progress, "en"), "pending")

    def test_text_renders_rolling_plan(self):
        text = daily_target_text(daily_target_progress(200, 147.4, "2026-09-18"))
        self.assertIn("6.67 万/天", text)
        self.assertIn("第 18/30 天", text)
        self.assertIn("累计应达 120.1 万", text)
        self.assertIn("领先 27.3 万", text)


class PerformanceNoiseTests(unittest.TestCase):
    """机器人模板回显与明确否定不能当成客户水单/意向。"""

    def _msg(self, body: str) -> dict:
        return {
            "sender_user_id": 13063,
            "message_type": "text",
            "body": body,
            "created_at": "2026-09-18T03:10:00Z",
        }

    def test_bot_template_echo_is_ignored(self):
        msgs = [
            self._msg("②水单（无）"),
            self._msg("③意向（无）"),
            self._msg("20:00 [晚追]：无 VPS 留痕记录、无Vemory 录音链接与无实际订单水单"),
            self._msg("请补：今天汽车/转B线索有没有聊、几轮、卡点、要什么支持。"),
        ]
        buckets = parse_performance_buckets(msgs, 13063)
        self.assertEqual(buckets["slip"], [])
        self.assertEqual(buckets["intent"], [])

    def test_real_slip_and_intent_still_captured(self):
        msgs = [
            self._msg("客户已回传水单 USD 45,000，等财务确认"),
            self._msg("迪拜客户明确意向 120万"),
        ]
        buckets = parse_performance_buckets(msgs, 13063)
        self.assertEqual(len(buckets["slip"]), 1)
        self.assertAlmostEqual(buckets["slip"][0]["wan"], 31.9, places=1)
        self.assertEqual(len(buckets["intent"]), 1)

    def test_negation_without_amount_is_ignored(self):
        buckets = parse_performance_buckets([self._msg("没有意向客户")], 13063)
        self.assertEqual(buckets["intent"], [])


class GroupTargetTests(unittest.TestCase):
    """新人小组这类“只对小组下目标”的口径：个人不摊人头，回查组目标。"""

    def test_member_resolves_group_target(self):
        from app.duzhan_ledger import group_target_of

        target = group_target_of("邓琳莹", "2026-09-18")
        self.assertIsNotNone(target)
        self.assertEqual(target[1], "新部")
        self.assertAlmostEqual(target[0], 100.0, places=1)

    def test_person_with_own_target_has_no_group_target(self):
        from app.duzhan_ledger import group_target_of

        self.assertIsNone(group_target_of("于冰", "2026-09-18"))

    def test_unknown_person_and_month(self):
        from app.duzhan_ledger import group_target_of

        self.assertIsNone(group_target_of("查无此人", "2026-09-18"))
        self.assertIsNone(group_target_of("邓琳莹", "2026-01-05"))


class PerformanceBucketTests(unittest.TestCase):
    def _msg(self, body: str) -> dict:
        return {
            "sender_user_id": 13063,
            "message_type": "text",
            "body": body,
            "created_at": "2026-09-18T03:10:00Z",
        }

    def test_amount_parsing_variants(self):
        self.assertEqual(_perf_amount("USD 45,000 水单已回传")["wan"], 31.9)
        self.assertEqual(_perf_amount("意向 120万")["wan"], 120.0)
        self.assertEqual(_perf_amount("600000 RMB 意向金")["wan"], 60.0)
        self.assertEqual(_perf_amount("3.5万 到账")["wan"], 3.5)
        self.assertEqual(_perf_amount("已付款，金额待确认")["text"], "")

    def test_buckets_split_by_keyword(self):
        messages = [
            self._msg("越南客户已付款，水单已回传 USD 45,000"),
            self._msg("迪拜客户明确意向 120万，本周确认"),
            self._msg("今日已到账 80万"),
            self._msg("今天聊了三个客户"),
        ]
        buckets = parse_performance_buckets(messages, 13063, arrived_wan=147.4)
        self.assertEqual(buckets["arrived"]["wan"], 147.4)
        self.assertEqual(len(buckets["arrived"]["mentions"]), 1)
        self.assertEqual(buckets["slip"][0]["wan"], 31.9)
        self.assertEqual(buckets["intent"][0]["wan"], 120.0)

    def test_other_sender_ignored(self):
        messages = [dict(self._msg("水单 USD 9,999"), sender_user_id=99999)]
        buckets = parse_performance_buckets(messages, 13063, arrived_wan=None)
        self.assertEqual(buckets["slip"], [])


class RenderCopyTests(unittest.TestCase):
    """文案回归：今日目标不得再显示部门口号；业绩三关键词必须出现。"""

    def _ledger(self) -> dict:
        progress = daily_target_progress(200, 147.4, "2026-09-18")
        person = {
            "group": "于冰业绩达标群",
            "display": "于冰",
            "target_wan": 200,
            "mtd_wan": 147.4,
            "perf_arrived_wan": 147.4,
            "perf_slip": [{"amount_text": "$45,000", "wan": 31.9, "snippet": "越南客户水单已回传"}],
            "perf_intent": [{"amount_text": "120万", "wan": 120.0, "snippet": "迪拜客户明确意向"}],
            "daily_target_wan": progress["daily_target"],
            "rolling_target_wan": progress["rolling_target"],
            "days_elapsed": progress["days_elapsed"],
            "days_in_month": progress["days_in_month"],
            "target_gap_wan": progress["gap"],
            "target_ahead": progress["ahead"],
        }
        return {"day": "2026-09-18", "today_target": "1300万战役", "people": [person], "red": [], "black": []}

    def test_brief_shows_rolling_target_and_buckets(self):
        group = next(g for g in groups_for_tz(TZ_SHANGHAI) if g.name == "于冰业绩达标群")
        text = render_brief(
            group, 10,
            datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            self._ledger(), None,
        )
        self.assertIn("滚动日目标：6.67 万/天", text)
        self.assertNotIn("今日目标：1300万战役", text, "1300万是月目标口号，不能占今日目标位")
        self.assertIn("业绩三关键词", text)
        # 老板 2026-09-18 拍板：括号里的解释说明去掉，标题已经说明口径
        self.assertIn("到账：147.4 万", text)
        self.assertIn("水单：$45,000", text)
        self.assertIn("意向：120万", text)
        self.assertNotIn("已录单，系统口径", text)


if __name__ == "__main__":
    unittest.main()
