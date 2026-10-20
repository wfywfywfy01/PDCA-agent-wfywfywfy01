"""Morning planning, brief midday follow-up, and detailed evening closure."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.daily_report import _configured_sales_target
from app.duzhan import GROUPS, is_own_bot_message, render_brief, render_person_briefs


class CheckinTests(TestCase):
    def setUp(self):
        self.group = next(g for g in GROUPS if g.name == "于冰业绩达标群")
        self.person = {
            "group": self.group.name, "display": "于冰", "target_wan": 160,
            "mtd_wan": 45, "perf_arrived_wan": 45, "daily_target_wan": 5.16,
            "rolling_target_wan": 103.2, "target_gap_wan": -58.2,
            "collections": [
                {"title": "客户A尾款", "status": "stalled", "progress": "待到账"},
                {"title": "客户B合同", "status": "done", "progress": "已完成"},
            ],
            "mto_count": 4, "mto_quotes": [], "wa_reached": 8,
            "intent_count": 2, "hours_minutes": 120,
            "blockers": ["客户A需财务核对"], "evidence": ["XSD-TEST"],
            "daily_report_ok": False,
        }
        self.ledger = {"day": "2026-10-20", "people": [self.person]}
        self.settings = patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=True))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.weekly = patch("app.weekly_focus.items_for", return_value=[{
            "who": "于冰", "text": "本周完成客户A合同", "text_en": "Finish customer A's contract this week",
        }])
        self.weekly.start()
        self.addCleanup(self.weekly.stop)
        self.meeting = patch("app.meeting_todos.items_for_group", return_value=[
            {"who": "于冰", "text": "今天提交报价"},
            {"who": "杨晶晶", "text": "其他人的待办"},
        ])
        self.meeting.start()
        self.addCleanup(self.meeting.stop)

    def render(self, hour, minute=0):
        now = datetime(2026, 10, 20, hour, minute, tzinfo=ZoneInfo(self.group.tz))
        return render_person_briefs(
            self.group, hour, now, self.ledger, self.ledger,
            minute=minute,
        )[0]["text"]

    def test_morning_is_goals_daily_weekly_and_mto_only(self):
        text = self.render(10)
        for item in ("1600", "二部800万", "三部400万", "四部200万", "一部200万", "五部破零",
                     "今日待办", "客户A尾款", "今天提交报价", "本周完成客户A合同", "MTO", "4款"):
            self.assertIn(item, text)
        for item in ("其他人的待办", "VPS 留痕", "工时", "日报核对", "1300万", "业绩三关键词"):
            self.assertNotIn(item, text)
        self.assertLess(len(text), 650)

    def test_midday_is_short_and_does_not_repeat_plans(self):
        text = self.render(15)
        self.assertIn("客户A尾款", text)
        self.assertIn("请回", text)
        for item in ("本周完成客户A合同", "1600", "MTO", "工时", "日报", "其他人的待办"):
            self.assertNotIn(item, text)
        self.assertLess(len(text), 350)
        self.assertLessEqual(len(text.splitlines()), 6)

    def test_evening_shows_closure_mto_report_and_next_action(self):
        text = self.render(20)
        for item in ("已完成1项", "未闭环1项", "客户B合同", "客户A尾款", "MTO", "日报核对", "明日第一动作"):
            self.assertIn(item, text)
        self.assertIn("待确认（日报群取数失败）", text)
        self.assertNotIn("未见今日正式日报", text)

    def test_custom_time_keeps_the_same_stage_contract(self):
        morning = self.render(9, 35)
        midday = self.render(14, 35)
        self.assertIn("09:35", morning)
        self.assertIn("本周完成客户A合同", morning)
        self.assertIn("14:35", midday)
        self.assertNotIn("本周完成客户A合同", midday)

    def test_short_headers_still_prevent_the_bot_from_answering_itself(self):
        for group in (self.group, next(g for g in GROUPS if g.lang == "en")):
            for hour in (10, 15, 20):
                with self.subTest(lang=group.lang, hour=hour):
                    now = datetime(2026, 10, 20, hour, tzinfo=ZoneInfo(group.tz))
                    text = render_brief(group, hour, now, focus_override="@海外渠道督战官 核对待办")
                    self.assertTrue(is_own_bot_message({}, text))

    def test_missing_amount_is_inline_in_the_short_task_reminder(self):
        self.person["perf_slip"] = [{"snippet": "客户A水单", "wan": None}]
        for hour, label in ((10, "今日待办："), (15, "未闭环：")):
            text = self.render(hour)
            line = next(line for line in text.splitlines() if line.startswith(label))
            self.assertIn("待补金额1条", line)
            self.assertNotIn("补一句：", text)
            if hour == 15:
                self.assertLessEqual(len(text.splitlines()), 6)

    def test_joint_meeting_owners_keep_the_task_in_the_responsible_persons_plan(self):
        group = next(g for g in GROUPS if g.name == "Lina业绩达标群")
        ledger = {"people": [{"group": group.name, "display": "Lina"}]}
        with patch("app.meeting_todos.items_for_group", return_value=[
            {"who": "丽娜&冯磊", "text": "Joint custom-phone delivery"},
        ]):
            text = render_person_briefs(
                group, 10, datetime(2026, 10, 20, 10, tzinfo=ZoneInfo(group.tz)), ledger,
            )[0]["text"]
        self.assertIn("Joint custom-phone delivery", text)

    def test_empty_business_ledger_keeps_independent_daily_and_weekly_tasks(self):
        self.weekly.stop()
        weekly = {"weeks": [{"start": "2026-10-19", "end": "2026-10-25", "items": [
            {"who": "于冰", "groups": [self.group.name], "text": "已布置的本周任务"},
            {"who": "Lina", "groups": ["Lina业绩达标群"], "text": "别的群周任务"},
        ]}]}
        with patch("app.weekly_focus._payload", return_value=weekly):
            text = render_brief(
                self.group, 10, datetime(2026, 10, 20, 10, tzinfo=ZoneInfo(self.group.tz)),
            )
        self.assertIn("于冰：今天提交报价", text)
        self.assertIn("于冰：已布置的本周任务", text)
        self.assertNotIn("别的群周任务", text)

    def test_malformed_target_structure_does_not_block_the_checkin(self):
        from app import daily_report

        for payload in ([], {"2026-10": []}, {"2026-10": {
            "department_target_wan": 1600, "departments": ["bad-row"],
        }}):
            with self.subTest(payload=payload), TemporaryDirectory() as tmp:
                target = Path(tmp) / "targets.json"
                target.write_text(json.dumps(payload), encoding="utf-8")
                with patch.object(daily_report, "_SALES_TARGETS_FILE", target):
                    text = self.render(10)
                self.assertIn("本月海外目标：待确认", text)
                self.assertIn("今日待办", text)

    def test_historical_long_mode_uses_the_confirmed_goal_instead_of_a_stale_slogan(self):
        self.ledger["today_target"] = "1300万战役"
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            text = self.render(10)
        self.assertIn("1600万", text)
        self.assertNotIn("1300万", text)


class OctoberTargetTests(TestCase):
    def test_confirmed_department_targets_and_break_zero(self):
        total, details = _configured_sales_target("2026-10")
        self.assertEqual(total, 16_000_000)
        self.assertEqual(details, [
            "经销商二部 800 万", "经销商三部 400 万", "经销商四部 200 万",
            "经销商一部 200 万", "经销商五部 破零",
        ])

    def test_editing_a_personal_plan_preserves_department_goals(self):
        root = Path(__file__).resolve().parents[1]
        configured = json.loads((root / "app/monthly_sales_targets.json").read_text(encoding="utf-8"))
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "targets.json"
            target.write_text(json.dumps(configured), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(root / "scripts/set_monthly_targets.py"),
                "--file", str(target), "--month", "2026-10", "--person", "于冰=160",
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(target.read_text(encoding="utf-8"))["2026-10"]
            self.assertEqual(saved["departments"], configured["2026-10"]["departments"])
            self.assertEqual(saved["department_target_wan"], 1600)
