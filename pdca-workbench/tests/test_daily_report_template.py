# -*- coding: utf-8 -*-
"""《海外渠道每日销售汇报模板》合规检查（2026-09-30 老板定版模板）。"""
import unittest
from contextlib import contextmanager

from app.daily_report_template import (
    check_template,
    detect_slot,
    looks_like_report,
    normalize,
    summarize,
)

FULL = """# 海外渠道每日销售汇报模板

## 一、基础信息
- 日期：2026 年 9 月 30 日
- 时段：15:00 ☐　20:00 ☑
- 负责人：何川
- 负责市场 / 客户：迪拜、阿曼

## 二、分市场（客户）进度
▍【迪拜 Al Fahim】
- 进度：订单进度 80% ｜ 回款进度 50%
- 金额：订单金额 USD 120,000 ｜ 预计回款 USD 60,000
- 订单 / 生产：新订单 Sample Watch X1 20 台，PI 已发
- 物流 / 交付：预计 10 月 8 日发货
- 回款：预计 10 月 10 日到账
- 售后 / 技术：暂无
- 产品培训 / 推广：已完成一场培训
- 其他：MTO 选品 2 款

## 三、当前卡点及需要的支持（Blockers）
| 客户 / 市场 | 具体卡点 | 需要谁 / 哪个团队支持 | 期望完成时间 |
| --- | --- | --- | --- |
| 迪拜 | 清关资料未齐 | 物流组 | 10 月 8 日 |

## 四、明日重点工作
1. 确认迪拜回款到账凭证
2. 完成阿曼门店陈列方案
"""

QUICK_15 = """日期：2026-09-30　时段：15:00
负责人：于冰
负责市场：英国
▍【英国 Selfridges】
- 进度：订单进度 30% ｜ 回款进度 0%
- 金额：订单金额 USD 45,000 ｜ 预计回款 USD 0
卡点：无卡点
"""

LEGACY_CARD = """提交人：潘贤俊；日期：2026-09-29；今日工作：11 条
1. 客户3，进度：0% -> 100%
2. 客户1业务沟通，进度：0% -> 100%
明日计划：3 条
"""


class CheckTemplateTests(unittest.TestCase):
    def test_full_2000_report_passes(self):
        verdict = check_template(FULL, submitter="何川")
        self.assertTrue(verdict["ok"], verdict["missing"])
        self.assertEqual(verdict["slot"], "20:00")
        self.assertGreaterEqual(verdict["blockers"], 1)
        self.assertGreaterEqual(verdict["tomorrow"], 1)

    def test_1500_quick_report_does_not_need_tomorrow(self):
        verdict = check_template(QUICK_15, submitter="于冰")
        self.assertTrue(verdict["ok"], verdict["missing"])
        self.assertEqual(verdict["slot"], "15:00")

    def test_full_width_and_chinese_date(self):
        text = FULL.replace("USD 120,000", "ＵＳＤ 120,000").replace("订单进度 80%", "订单进度 ８０％")
        verdict = check_template(text, submitter="何川")
        self.assertTrue(verdict["ok"], verdict["missing"])

    def test_missing_cash_progress(self):
        verdict = check_template(FULL.replace("回款进度 50%", "回款进度待定"), submitter="何川")
        self.assertIn("回款进度百分比", verdict["missing"])

    def test_missing_usd_amount(self):
        verdict = check_template(FULL.replace("USD 120,000", "12 万").replace("USD 60,000", "6 万"), submitter="何川")
        self.assertIn("USD 金额", verdict["missing"])

    def test_blocker_row_missing_owner(self):
        text = FULL.replace("| 迪拜 | 清关资料未齐 | 物流组 | 10 月 8 日 |", "| 迪拜 | 清关资料未齐 |  | 10 月 8 日 |")
        verdict = check_template(text, submitter="何川")
        self.assertIn("卡点需要谁支持", verdict["missing"])

    def test_blocker_row_missing_deadline(self):
        text = FULL.replace("| 迪拜 | 清关资料未齐 | 物流组 | 10 月 8 日 |", "| 迪拜 | 清关资料未齐 | 物流组 | 尽快 |")
        verdict = check_template(text, submitter="何川")
        self.assertIn("卡点期望完成时间", verdict["missing"])

    def test_missing_blocker_section(self):
        text = FULL.split("## 三、")[0] + "## 四、明日重点工作\n1. 确认迪拜回款到账凭证\n"
        verdict = check_template(text, submitter="何川")
        self.assertIn("卡点章节", verdict["missing"])

    def test_explicit_no_blocker_is_accepted(self):
        verdict = check_template(FULL.replace("| 迪拜 | 清关资料未齐 | 物流组 | 10 月 8 日 |", "无卡点"), submitter="何川")
        self.assertNotIn("卡点章节", verdict["missing"])
        self.assertNotIn("卡点内容", verdict["missing"])

    def test_tomorrow_all_empty_talk(self):
        text = FULL.replace("1. 确认迪拜回款到账凭证", "1. 继续跟进").replace("2. 完成阿曼门店陈列方案", "2. 持续跟进")
        verdict = check_template(text, submitter="何川")
        self.assertIn("明日重点", verdict["missing"])
        self.assertEqual(verdict["tomorrow"], 0)

    def test_tomorrow_mixed_still_flagged(self):
        text = FULL.replace("1. 确认迪拜回款到账凭证", "1. 继续跟进")
        verdict = check_template(text, submitter="何川")
        self.assertIn("明日重点(空话)", verdict["missing"])
        self.assertEqual(verdict["tomorrow"], 1)

    def test_legacy_card_is_not_template_compliant(self):
        verdict = check_template(LEGACY_CARD, submitter="潘贤俊")
        self.assertFalse(verdict["ok"])
        for item in ("时段(15:00/20:00)", "负责市场/客户", "订单进度百分比", "卡点章节"):
            self.assertIn(item, verdict["missing"])

    def test_empty_text_reports_everything(self):
        verdict = check_template("", submitter="")
        self.assertFalse(verdict["ok"])
        self.assertGreaterEqual(len(verdict["missing"]), 9)

    def test_submitter_backs_the_owner_field(self):
        text = FULL.replace("- 负责人：何川\n", "")
        with_name = check_template(text, submitter="何川")
        without = check_template(text)
        self.assertNotIn("负责人", with_name["missing"])
        self.assertIn("负责人", without["missing"])

    def test_detect_slot(self):
        self.assertEqual(detect_slot("时段：20:00"), "20:00")
        self.assertEqual(detect_slot("15 点快报"), "15:00")
        self.assertEqual(detect_slot("今天没有时段"), "")

    def test_normalize_full_width(self):
        self.assertEqual(normalize("ＵＳＤ　１２０，０００"), "USD 120,000")

    def test_looks_like_report(self):
        self.assertTrue(looks_like_report(FULL))
        self.assertTrue(looks_like_report(QUICK_15))
        self.assertFalse(looks_like_report("🎉🎉🎉"))
        self.assertFalse(looks_like_report(LEGACY_CARD))
        self.assertFalse(looks_like_report(""))

    def test_summarize(self):
        self.assertEqual(summarize({"ok": True, "missing": []}), "模板合规")
        self.assertTrue(summarize({"ok": False, "missing": ["USD 金额", "卡点章节"]}).startswith("缺 USD 金额"))
        self.assertEqual(summarize({"ok": True, "missing": []}, lang="en"), "template ok")


class PipelineWiringTests(unittest.TestCase):
    """接进台账与群文案：文本归集、红黑榜缺口、群里那一行怎么写。"""

    def test_daily_report_texts_merges_card_and_template_text(self):
        from app.duzhan_ledger import daily_report_texts

        messages = [
            {
                "sender_user_id": 14640,
                "metadata": {
                    "kind": "daily_report_submission",
                    "work_date": "2026-09-30",
                    "submitter_user_id": 14640,
                    "fields": [{"label": "提交人", "value": "何川"}],
                    "items": ["1. 客户3，进度：0% -> 100%"],
                    "tomorrow": ["确认回款"],
                },
                "body": "何川 已提交 2026-09-30 日报",
            },
            {"sender_user_id": 14640, "metadata": {}, "body": FULL},
            {"sender_user_id": 999, "metadata": {}, "body": "别人说的话"},
            {
                "sender_user_id": 888,
                "metadata": {"kind": "daily_report_submission", "work_date": "2026-09-29", "fields": []},
                "body": "",
            },
        ]
        texts = daily_report_texts(messages, "2026-09-30")
        # 归集按发送人分桶（谁在群里说话就有谁的桶），但只有像日报的才当日报
        self.assertIn("14640", texts)
        self.assertIn("何川", texts["14640"])
        self.assertIn("确认回款", texts["14640"])
        self.assertIn("明日重点工作", texts["14640"])
        self.assertFalse(looks_like_report(texts["999"]), "群里闲聊不能算日报")
        self.assertFalse(looks_like_report(texts.get("888", "")))

    @contextmanager
    def _compact_off(self):
        """生产是 PDCA_DUZHAN_COMPACT=0（长版）；测试里固定住，别依赖跑测试的机器环境。"""
        from types import SimpleNamespace
        from unittest.mock import patch

        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            yield

    def _ledger_with_report(self, day: str, report: dict):
        from app.duzhan import GROUPS
        from app.duzhan_ledger import empty_ledger

        group = GROUPS[0]
        person = {
            "display": "邓琳莹",
            "group": group.name,
            "daily_report": report,
            "hours_minutes": 120,
            "collections": [{"title": "客户跟进", "progress": "100%"}],
        }
        ledger = empty_ledger(day)
        ledger["people"] = [person]
        prev = empty_ledger(day)
        prev["people"] = [dict(person)]
        return group, ledger, prev

    def test_afternoon_variant_keeps_the_report_line(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.duzhan import render_brief

        report = {
            "spent_hours": 6,
            "item_count": 3,
            "done_count": 2,
            "template": {"ok": False, "slot": "15:00", "missing": ["USD 金额", "卡点章节"]},
        }
        group, ledger, prev = self._ledger_with_report("2026-10-09", report)
        with self._compact_off():
            body = render_brief(group, 15, datetime(2026, 10, 9, 15, 0, tzinfo=ZoneInfo(group.tz)), ledger, prev)
        self.assertIn("日报核对：", body)
        self.assertIn("模板缺2项", body)
        self.assertIn("USD 金额", body)

    def test_evening_variant_keeps_the_report_line(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.duzhan import render_brief

        report = {
            "spent_hours": 6,
            "item_count": 3,
            "done_count": 3,
            "template": {"ok": True, "slot": "20:00", "missing": []},
        }
        group, ledger, prev = self._ledger_with_report("2026-10-09", report)
        with self._compact_off():
            body = render_brief(group, 20, datetime(2026, 10, 9, 20, 0, tzinfo=ZoneInfo(group.tz)), ledger, prev)
        self.assertIn("日报核对：", body)
        self.assertIn("模板合规", body)

    def test_evening_variant_marks_missing_report(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.duzhan import render_brief

        group, ledger, prev = self._ledger_with_report("2026-10-09", {})
        with self._compact_off():
            body = render_brief(group, 20, datetime(2026, 10, 9, 20, 0, tzinfo=ZoneInfo(group.tz)), ledger, prev)
        self.assertIn("日报核对：未见今日正式日报", body)

    def test_report_line_shows_missing_items(self):
        from app.duzhan import _daily_report_text

        person = {
            "hours_minutes": 120,
            "daily_report": {
                "spent_hours": 4,
                "item_count": 3,
                "done_count": 1,
                "template": {"ok": False, "slot": "20:00", "missing": ["USD 金额", "卡点章节", "明日重点"]},
            },
        }
        zh = _daily_report_text(person, "zh")
        self.assertIn("模板缺3项", zh)
        self.assertIn("USD 金额", zh)
        self.assertIn("申报4h", zh)
        en = _daily_report_text(person, "en")
        self.assertIn("template missing", en)

    def test_report_line_calls_out_compliant_report(self):
        from app.duzhan import _daily_report_text

        person = {
            "hours_minutes": 60,
            "daily_report": {
                "spent_hours": 2,
                "item_count": 2,
                "done_count": 2,
                "template": {"ok": True, "slot": "15:00", "missing": []},
            },
        }
        zh = _daily_report_text(person, "zh")
        self.assertIn("模板合规", zh)
        self.assertNotIn("模板缺", zh)

    def test_pending_and_missing_are_unchanged(self):
        from app.duzhan import _daily_report_text

        self.assertIn("待确认", _daily_report_text({"daily_report_ok": False}, "zh"))
        self.assertIn("未见今日正式日报", _daily_report_text({"daily_report_ok": True}, "zh"))

    def test_score_row_flags_missing_template_items(self):
        from app.duzhan_ledger import PersonRow, score_row

        row = PersonRow(group="示例群", display="何川")
        row.daily_report = {
            "submitted": True,
            "items": [{"progress": 100}],
            "template": {"ok": False, "slot": "20:00", "missing": ["USD 金额", "卡点章节"]},
        }
        scored = score_row(row)
        self.assertIn("日报缺2项", scored.gaps)
        self.assertNotIn("未报今日任务", scored.gaps)

    def test_text_only_submission_is_not_counted_as_missing(self):
        from app.duzhan_ledger import PersonRow, score_row

        row = PersonRow(group="示例群", display="于冰")
        row.daily_report = {"submitted": True, "items": [], "from": "text", "template": {"ok": True}}
        scored = score_row(row)
        self.assertNotIn("未报今日任务", scored.gaps)


if __name__ == "__main__":
    unittest.main()
