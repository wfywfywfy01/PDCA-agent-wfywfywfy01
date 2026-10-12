# -*- coding: utf-8 -*-
"""本周任务（老板 2026-10-10）：按人挂一周任务，命中就每天追，过期收起。"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import weekly_focus
from app.duzhan import GROUPS, render_person_briefs
from app.duzhan_ledger import empty_ledger

WEEK = ("2026-10-10", "2026-10-16")
TEXT = "对标“佳佳说”这个视频号，做出同质量的AI视频"


class BlockTests(unittest.TestCase):
    def test_hits_the_three_people(self):
        cases = [
            ("viki业绩达标群", "Viki"),
            ("杨晶晶业绩达标群", "杨晶晶"),
            ("Lina业绩达标群", "Lina"),
        ]
        for group_name, display in cases:
            with self.subTest(display=display):
                block = weekly_focus.block_for("2026-10-12", group_name, display)
                self.assertIn("本周任务", block)
                self.assertIn("佳佳说", block)

    def test_alias_matches_the_chinese_name(self):
        # 台账里显示名是 Viki，任务写的是尤文静
        self.assertIn("佳佳说", weekly_focus.block_for("2026-10-12", "viki业绩达标群", "Viki"))

    def test_other_people_and_groups_are_not_chased(self):
        self.assertEqual(weekly_focus.block_for("2026-10-12", "viki业绩达标群", "江旭"), "")
        self.assertEqual(weekly_focus.block_for("2026-10-12", "于冰业绩达标群", "于冰"), "")

    def test_window_is_closed_interval_and_then_expires(self):
        self.assertTrue(weekly_focus.block_for(WEEK[0], "viki业绩达标群", "Viki"))
        self.assertTrue(weekly_focus.block_for(WEEK[1], "viki业绩达标群", "Viki"))
        self.assertEqual(weekly_focus.block_for("2026-10-09", "viki业绩达标群", "Viki"), "")
        self.assertEqual(weekly_focus.block_for("2026-10-17", "viki业绩达标群", "Viki"), "")

    def test_english_group_uses_translated_text(self):
        block = weekly_focus.block_for("2026-10-12", "Lina业绩达标群", "Lina", lang="en")
        self.assertIn("Jiajia Shuo", block)
        self.assertNotIn("本周任务", block)

    def test_runtime_file_overrides_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "weekly_focus.json").write_text(json.dumps({
                "weeks": [{
                    "start": "2026-10-10",
                    "end": "2026-10-16",
                    "label": "本周任务",
                    "items": [{"who": "于冰", "groups": ["于冰业绩达标群"], "text": "临时换的任务"}],
                }]
            }, ensure_ascii=False), encoding="utf-8")
            with patch.object(weekly_focus, "get_settings", return_value=SimpleNamespace(data_dir=Path(tmp))):
                self.assertIn("临时换的任务", weekly_focus.block_for("2026-10-12", "于冰业绩达标群", "于冰"))
                self.assertEqual(weekly_focus.block_for("2026-10-12", "viki业绩达标群", "Viki"), "")

    def test_empty_config_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "none.json"
            empty.write_text("{}", encoding="utf-8")
            with patch.object(weekly_focus, "FOCUS_FILE", empty), patch.object(
                weekly_focus, "get_settings", return_value=SimpleNamespace(data_dir=Path(tmp))
            ):
                self.assertEqual(weekly_focus.block_for("2026-10-12", "viki业绩达标群", "Viki"), "")


class RenderTests(unittest.TestCase):
    def _ledger(self) -> dict:
        ledger = empty_ledger("2026-10-12")
        ledger["people"] = [
            {"display": "Viki", "group": "viki业绩达标群"},
            {"display": "江旭", "group": "viki业绩达标群"},
            {"display": "Lina", "group": "Lina业绩达标群"},
        ]
        return ledger

    def test_weekly_task_lands_in_the_per_person_message(self):
        group = next(g for g in GROUPS if g.name == "viki业绩达标群")
        now = datetime(2026, 10, 12, 20, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(group, 20, now, self._ledger(), self._ledger())
        by_name = {part["display"]: part["text"] for part in parts}
        self.assertIn("佳佳说", by_name["Viki"])
        self.assertNotIn("佳佳说", by_name["江旭"], "没被点名的人不该看到这条任务")

    def test_no_task_after_the_week_ends(self):
        group = next(g for g in GROUPS if g.name == "viki业绩达标群")
        now = datetime(2026, 10, 19, 20, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(group, 20, now, self._ledger(), self._ledger())
        self.assertNotIn("佳佳说", "".join(part["text"] for part in parts))


if __name__ == "__main__":
    unittest.main()
