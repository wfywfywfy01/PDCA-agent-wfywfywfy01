# -*- coding: utf-8 -*-
"""2026-09-22 拍板的回归：早会待办第 8 节 / MTO 摘要行 / 长假豁免语义。"""
from __future__ import annotations

import unittest


class MeetingTodosTests(unittest.TestCase):
    def test_full_report_includes_meeting_todos_exactly_once(self):
        from app.duzhan import GROUPS, _full_person_body

        block = "8. 早会待办：\n- 确认客户方案与截止时间\n"
        for hour in (10, 15, 20):
            with self.subTest(hour=hour):
                text = _full_person_body(GROUPS[0], hour, {"meeting_todos": block}, "zh")
                self.assertEqual(text.count(block), 1)
                self.assertNotIn("8. 早会待办", _full_person_body(GROUPS[0], hour, None, "zh"))

    def test_group_items_are_isolated(self):
        from app.meeting_todos import block_for_group

        viki = block_for_group("2026-09-20", "viki业绩达标群")
        lina = block_for_group("2026-09-20", "Lina业绩达标群")
        self.assertIn("尤文静", viki)
        self.assertNotIn("丽娜", viki)
        self.assertIn("丽娜&冯磊", lina)
        self.assertNotIn("尤文静", lina)

    def test_mgmt_items_never_reach_group_versions(self):
        from app.meeting_todos import block_for_group, block_for_mgmt

        mgmt = block_for_mgmt("2026-09-20")
        self.assertIn("JIM", mgmt)
        self.assertIn("付汪洋", mgmt)
        for group in ("viki业绩达标群", "Lina业绩达标群", "新人小组业绩达标群", "于冰业绩达标群"):
            text = block_for_group("2026-09-20", group)
            self.assertNotIn("JIM", text, group)
            self.assertNotIn("付汪洋", text, group)

    def test_no_items_means_no_section(self):
        from app.meeting_todos import block_for_group, block_for_mgmt

        self.assertEqual(block_for_group("2026-01-01", "viki业绩达标群"), "")
        self.assertEqual(block_for_mgmt("2026-01-01"), "")

    def test_person_row_carries_todos_field(self):
        from app.duzhan_ledger import PersonRow

        self.assertEqual(PersonRow(group="viki业绩达标群", display="Viki").meeting_todos, "")


class MtoSummaryTests(unittest.TestCase):
    def test_summary_text(self):
        from app.duzhan import _mto_summary

        person = {
            "mto_quotes": [
                {"model": "VertuAlphafold", "wan": 44.2, "qualifies": True},
                {"model": "VertuQuantum", "wan": 22.8, "qualifies": False},
                {"model": "", "wan": None, "qualifies": False},
            ]
        }
        text = _mto_summary(person, "zh")
        self.assertIn("1 款达标", text)
        self.assertIn("VertuAlphafold 44.2万", text)
        self.assertIn("未满 30 万", text)
        self.assertIn("读不出金额", text)

    def test_summary_pending_when_no_data(self):
        from app.duzhan import _mto_summary

        self.assertEqual(_mto_summary({"mto_count": None}, "zh"), "待确认")
        self.assertEqual(_mto_summary({}, "zh"), "待确认")


class PenaltyExemptTests(unittest.TestCase):
    def test_makeup_day_is_not_exempt(self):
        from app.workday_calendar import day_kind, is_workday, penalty_exempt

        self.assertEqual(day_kind("2026-09-20"), "makeup")
        self.assertTrue(is_workday("2026-09-20"))
        self.assertFalse(penalty_exempt("2026-09-20"), "调休补班日照常评价")

    def test_long_holiday_is_exempt_but_pushed(self):
        from app.workday_calendar import day_kind, is_workday, penalty_exempt

        for day in ("2026-09-25", "2026-10-03"):
            self.assertEqual(day_kind(day), "long_holiday")
            self.assertTrue(is_workday(day), "长假照推")
            self.assertTrue(penalty_exempt(day), "长假不处罚")

    def test_rest_day_is_skipped(self):
        from app.workday_calendar import is_workday, penalty_exempt

        self.assertFalse(is_workday("2026-09-19"))
        self.assertFalse(penalty_exempt("2026-09-19"))


if __name__ == "__main__":
    unittest.main()
