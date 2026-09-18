# -*- coding: utf-8 -*-
"""海外日报群总结（08:00 总分结构）测试。

只测渲染与口径，不发群、不联网：台账由夹具直接提供。
"""
from __future__ import annotations

import unittest
from unittest import mock

from app.daily_digest import (
    _prev_day,
    _window_text,
    build_digest,
    push_digest,
)


def _person(name: str, group: str, **over: object) -> dict:
    row = {
        "group": group,
        "display": name,
        "target_wan": 200.0,
        "mtd_wan": 170.2,
        "perf_arrived_wan": 170.2,
        "perf_slip": [],
        "perf_intent": [],
        "mto_count": 3,
        "hours_minutes": 480.0,
        "wa_reached": 12,
        "daily_report": {"item_count": 4, "spent_hours": 8},
        "collections": [{"title": "索契水单", "status": "open"}],
        "blockers": ["等客户回复"],
        "daily_target_wan": 6.67,
        "rolling_target_wan": 120.1,
        "days_elapsed": 18,
        "days_in_month": 30,
        "target_gap_wan": 50.1,
        "target_ahead": True,
    }
    row.update(over)
    return row


def _ledger(people: list[dict]) -> dict:
    return {"day": "2026-09-18", "people": people, "red": [], "black": []}


class DigestStructureTests(unittest.TestCase):
    def test_prev_day_and_window(self):
        self.assertEqual(_prev_day("2026-09-19"), "2026-09-18")
        self.assertEqual(_prev_day("bad"), "bad")
        text = _window_text("2026-09-19", "2026-09-18")
        self.assertIn("09-18 08:00 → 09-19 08:00", text)
        self.assertIn("数据日 2026-09-18", text)

    def test_sections_in_total_to_detail_order(self):
        led = _ledger(
            [
                _person("于冰", "于冰业绩达标群"),
                _person("何海文", "杨晶晶业绩达标群", mtd_wan=95.0, perf_arrived_wan=95.0),
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        order = [
            "一、大部门",
            "二、小部门",
            "三、个人明细",
            "四、明日预告（昨日未闭环 → 今天第一动作）",
            "五、卡点与需拍板",
        ]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("【海外渠道日报｜2026-09-19 08:00】", text)
        self.assertIn("海外事业部", text)

    def test_department_and_group_target_use_ledger_day(self):
        led = _ledger([_person("于冰", "于冰业绩达标群")])
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        # 部门月目标 1228 万 ÷ 30 天 = 40.93 万/天，第 18 天累计应达 736.8 万
        self.assertIn("月目标 1228 万", text)
        self.assertIn("第 18/30 天", text)

    def test_bucket_amounts_pending_when_unreadable(self):
        led = _ledger(
            [
                _person(
                    "于冰",
                    "于冰业绩达标群",
                    perf_slip=[{"amount_text": "", "wan": None, "snippet": "水单已回传，金额在邮件里"}],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("水单 1 笔（金额待确认）", text)
        self.assertNotIn("水单 1 笔（0 万）", text)

    def test_three_buckets_kept_apart(self):
        led = _ledger(
            [
                _person(
                    "于冰",
                    "于冰业绩达标群",
                    perf_slip=[{"amount_text": "USD 45,022", "wan": 32.0, "snippet": "水单已回传"}],
                    perf_intent=[{"amount_text": "120万", "wan": 120.0, "snippet": "明确意向"}],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("水单 1 笔（32 万）", text)
        self.assertIn("意向 1 笔（120 万）", text)
        self.assertIn("USD 45,022", text)

    def test_missing_values_render_pending_not_zero(self):
        led = _ledger(
            [
                _person(
                    "Lina",
                    "Lina业绩达标群",
                    mtd_wan=None,
                    perf_arrived_wan=None,
                    mto_count=None,
                    wa_reached=None,
                    hours_minutes=None,
                    daily_report={},
                    target_wan=None,
                    daily_target_wan=None,
                    rolling_target_wan=None,
                    target_gap_wan=None,
                    collections=[],
                    blockers=[],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("累计到账 待确认", text)
        self.assertIn("MTO 待确认", text)
        self.assertIn("WhatsApp 待确认", text)
        self.assertIn("工时 待确认", text)
        self.assertIn("未见日报", text)
        self.assertIn("1 人未出数", text)
        self.assertIn("水单 未检索到", text)
        self.assertNotIn("0 万", text)

    def test_unfinished_and_blockers_are_carried(self):
        led = _ledger(
            [
                _person(
                    "于冰",
                    "于冰业绩达标群",
                    collections=[
                        {"title": "索契水单", "status": "open"},
                        {"title": "已办完", "status": "done"},
                    ],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("索契水单", text)
        self.assertNotIn("已办完", text)
        self.assertIn("等客户回复", text)

    def test_empty_people_says_pending_not_fabricated(self):
        text = build_digest("2026-09-19", _ledger([]), ledger_day="2026-09-18")
        self.assertIn("未检索到未闭环事项", text)
        self.assertIn("未见卡点上报", text)
        self.assertIn("月目标 1228 万", text)      # 部门目标来自目标文件，与人数无关
        self.assertIn("到账 待确认", text)          # 没有一人出数，不编 0
        self.assertIn("未取到人员台账", text)


    def test_newcomer_group_target_from_file_members(self):
        # 「新部 100 万」在目标文件里以 members 形式给出：个人目标缺失时按组目标显示
        led = _ledger(
            [
                _person("邓琳莹", "新人小组业绩达标群", target_wan=None, daily_target_wan=None),
                _person("Safae", "新人小组业绩达标群", target_wan=None, daily_target_wan=None),
                _person("王宇彤", "新人小组业绩达标群", target_wan=None, daily_target_wan=None),
                _person("张月馨", "新人小组业绩达标群", target_wan=None, daily_target_wan=None),
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("新人小组业绩达标群（邓琳莹 / Safae / 王宇彤 / 张月馨）", text)
        self.assertIn("月目标 100 万", text)

    def test_individual_line_uses_group_level_target(self):
        led = _ledger(
            [
                _person(
                    "邓琳莹",
                    "新人小组业绩达标群",
                    target_wan=None,
                    daily_target_wan=None,
                    group_target_wan=100.0,
                    group_target_name="新部",
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("日目标 按新部整体算（100 万/月）", text)

    def test_blocker_section_excludes_daily_plan(self):
        led = _ledger(
            [
                _person(
                    "邓琳莹",
                    "新人小组业绩达标群",
                    blockers=["今日计划 1.触达名单30个 2.MTO高定图制作2款", "客户迟迟未回复水单"],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertNotIn("今日计划", text)
        self.assertIn("客户迟迟未回复水单", text)

    def test_plan_text_with_reply_wording_is_still_not_a_blocker(self):
        # 新人组晨夕会模板里“未回复的执行3/7/14方式”是流程说明，不是卡点
        led = _ledger(
            [
                _person(
                    "邓琳莹",
                    "新人小组业绩达标群",
                    blockers=[
                        "今日计划 1.触达名单30个 4.跟进有回复，未回复的执行3/7/14方式二次触达 5.新人组晨夕会",
                    ],
                )
            ]
        )
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("未见卡点上报", text)

    def test_red_board_does_not_fake_zero_amount(self):
        led = _ledger([_person("于冰", "于冰业绩达标群")])
        led["red"] = [{"display": "邓琳莹", "mtd_wan": 0.0, "score": 12}]
        led["black"] = [{"display": "Lina", "reason": "任务完成0/12；逾期2项"}]
        text = build_digest("2026-09-19", led, ledger_day="2026-09-18")
        self.assertIn("红榜（过程完成度）", text)
        self.assertIn("@邓琳莹 12 分｜本月未出单", text)
        self.assertNotIn("累计0万", text)
        self.assertIn("黑榜（待改进）", text)


class DigestPushTests(unittest.TestCase):
    def test_dry_run_does_not_send(self):
        led = _ledger([_person("于冰", "于冰业绩达标群")])
        with mock.patch("app.daily_digest.collect_ledger", return_value=led):
            result = push_digest("2026-09-19", dry_run=True)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "dry_run")
        self.assertIn("preview", result)

    def test_group_send_without_channel_fails_loudly(self):
        from app.todos.service import send_group_text

        ok, reason, via = send_group_text("", "正文", "cid-1")
        self.assertFalse(ok)
        self.assertIn("channel_id", reason)
        self.assertEqual(via, "")


class DigestJobRegistrationTests(unittest.TestCase):
    """08:00 注册 + 08:30 备份（共享 claim 台账，绝不重复推群）。"""

    def _register(self, **over: object):
        from types import SimpleNamespace

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
            "daily_digest_enabled": True,
            "daily_digest_time": "08:00",
        }
        base.update(over)
        settings = SimpleNamespace(**base)
        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        try:
            with mock.patch.object(
                scheduler_jobs, "get_settings", return_value=settings
            ), mock.patch.object(
                scheduler_jobs, "BackgroundScheduler", RecordingScheduler
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        jobs = {
            kwargs["id"]: (kwargs["hour"], kwargs["minute"])
            for _, _, kwargs in scheduler.jobs
            if str(kwargs.get("id", "")).startswith("daily_digest")
        }
        funcs = {
            kwargs["id"]: func
            for func, _, kwargs in scheduler.jobs
            if str(kwargs.get("id", "")).startswith("daily_digest")
        }
        return jobs, funcs

    def test_disabled_registers_nothing(self):
        jobs, _ = self._register(daily_digest_enabled=False)
        self.assertEqual(jobs, {})

    def test_enabled_registers_0800_with_0830_backup(self):
        jobs, funcs = self._register()
        self.assertEqual(jobs["daily_digest"], (8, 0))
        self.assertEqual(jobs["daily_digest_backup"], (8, 30))

    def test_backup_wraps_past_midnight(self):
        jobs, _ = self._register(daily_digest_time="23:50")
        self.assertEqual(jobs["daily_digest"], (23, 50))
        self.assertEqual(jobs["daily_digest_backup"], (0, 20))

    def test_illegal_time_is_ignored_not_crashing(self):
        jobs, _ = self._register(daily_digest_time="八点")
        self.assertEqual(jobs, {})


if __name__ == "__main__":
    unittest.main()
