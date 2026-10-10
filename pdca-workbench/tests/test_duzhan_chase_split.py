# -*- coding: utf-8 -*-
"""老板 2026-10-10 拍板的三件事：群/人重排、按人拆开发、停发红黑榜。

1. 新人小组群停推；新增 Q4五百万群；
2. 各组长群只追指定的人（谁追谁对应到人，各算各的）；
3. 20:00 那一版不再带红榜/黑榜/奖励台账/扣罚台账。
"""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.duzhan import (
    GROUPS,
    TZ_SHANGHAI,
    render_brief,
    render_person_briefs,
)
from app.duzhan_ledger import OWNERS, empty_ledger

XINREN = "850d06d0-5dd8-4a43-ad35-1cb3fcf6d484"
Q4 = "b0f2deaf-dea1-463a-98dd-970a1ddd1415"

#: 老板 2026-10-10 指定：群名 -> 追谁（顺序也按这个）
EXPECTED = {
    "于冰业绩达标群": ["于冰"],
    "杨晶晶业绩达标群": ["杨晶晶", "何海文", "王宇彤"],
    "viki业绩达标群": ["Viki", "江旭", "张月馨"],
    "Lina业绩达标群": ["Lina", "Safae"],
    "Q4五百万": ["刘春梅", "邓琳莹"],
}


def roster_by_group() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for owner in OWNERS:
        out.setdefault(owner.group, []).append(owner.display)
    return out


class GroupConfigTests(unittest.TestCase):
    def test_xinren_group_is_retired(self):
        self.assertNotIn(XINREN, {g.channel_id for g in GROUPS})
        self.assertNotIn("新人小组业绩达标群", {g.name for g in GROUPS})

    def test_q4_group_is_registered_on_shanghai_clock(self):
        q4 = next((g for g in GROUPS if g.name == "Q4五百万"), None)
        self.assertIsNotNone(q4, "Q4五百万 必须进三追群清单")
        self.assertEqual(q4.channel_id, Q4)
        self.assertEqual(q4.tz, TZ_SHANGHAI)
        self.assertEqual(q4.lang, "zh")

    def test_roster_matches_the_boss_list(self):
        self.assertEqual(roster_by_group(), EXPECTED)

    def test_nobody_is_chased_by_two_groups(self):
        seen: list[str] = []
        for names in EXPECTED.values():
            seen += names
        self.assertEqual(len(seen), len(set(seen)), "同一个人只能被一个群追")


class SplitMessageTests(unittest.TestCase):
    def _ledger(self) -> dict:
        entry = empty_ledger("2026-10-10")
        entry["people"] = [
            {
                "display": name,
                "group": group,
                "target_wan": 20,
                "mtd_wan": 1.5,
                "collections": [{"title": "客户跟进", "progress": "100%"}],
            }
            for group, names in EXPECTED.items()
            for name in names
        ]
        return entry

    def test_each_person_gets_their_own_message(self):
        ledger = self._ledger()
        group = next(g for g in GROUPS if g.name == "杨晶晶业绩达标群")
        now = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(group, 10, now, ledger)
        self.assertEqual([p["display"] for p in parts], ["杨晶晶", "何海文", "王宇彤"])
        for part in parts:
            self.assertIn(part["display"], part["text"], "每条消息要对应到人")
            self.assertNotIn("汇报人：杨晶晶 / 何海文", part["text"], "不能再合并成一条")

    def test_group_level_todos_appear_only_once(self):
        ledger = self._ledger()
        for person in ledger["people"]:
            if person["group"] == "杨晶晶业绩达标群":
                person["meeting_todos"] = "\n【今日早会待办】\n   • 杨晶晶：示例待办"
        group = next(g for g in GROUPS if g.name == "杨晶晶业绩达标群")
        now = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(group, 10, now, ledger)
        hits = [p["display"] for p in parts if "今日早会待办" in p["text"]]
        self.assertEqual(len(hits), 1, f"群级待办只该出现一次，实际 {hits}")

    def test_group_without_roster_still_sends_one_placeholder(self):
        group = next(g for g in GROUPS if g.name == "于冰业绩达标群")
        now = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(group, 10, now, empty_ledger("2026-10-10"))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["display"], "")

    def test_board_is_not_in_the_group_message(self):
        ledger = self._ledger()
        ledger["red"] = [{"display": "邓琳莹", "reason": "示例"}]
        ledger["black"] = [{"display": "何海文", "reason": "未报今日任务"}]
        ledger["penalties"] = [{"zh": "示例扣罚", "en": "sample"}]
        group = next(g for g in GROUPS if g.name == "杨晶晶业绩达标群")
        now = datetime(2026, 10, 10, 20, 0, tzinfo=ZoneInfo(group.tz))
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            body = render_brief(group, 20, now, ledger, ledger)
        for token in ("红榜", "黑榜", "奖励台账", "扣罚台账"):
            self.assertNotIn(token, body)


class PushPerPersonTests(unittest.TestCase):
    def test_run_duzhan_pushes_one_message_per_person(self):
        from app import duzhan as dz

        group = next(g for g in GROUPS if g.name == "杨晶晶业绩达标群")
        snapshot = {
            "messages": {group.channel_id: "合并版（不应被用）"},
            "person_messages": {
                group.channel_id: [
                    {"display": "杨晶晶", "text": "杨晶晶的档"},
                    {"display": "何海文", "text": "何海文的档"},
                    {"display": "王宇彤", "text": "王宇彤的档"},
                ]
            },
            "ledger": empty_ledger("2026-10-10"),
        }
        pushed: list[tuple[str, str]] = []
        with patch.object(dz, "load_prepared", return_value=snapshot), patch.object(
            dz, "groups_for_tz", return_value=[group]
        ), patch.object(
            dz, "push_duzhan_message", side_effect=lambda body, channel, idempotency_key="": pushed.append(
                (body, idempotency_key)
            ) or True
        ):
            result = dz.run_duzhan(
                TZ_SHANGHAI, 20, datetime(2026, 10, 10, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
            )
        self.assertEqual([body for body, _ in pushed], ["杨晶晶的档", "何海文的档", "王宇彤的档"])
        keys = [key for _, key in pushed]
        self.assertEqual(len(keys), len(set(keys)), "每个人的幂等键必须不同")
        self.assertEqual(result["messages"], 3)
        self.assertEqual(result["sent"], ["杨晶晶业绩达标群"])

    def test_run_duzhan_falls_back_to_group_message_for_old_snapshot(self):
        from app import duzhan as dz

        group = next(g for g in GROUPS if g.name == "于冰业绩达标群")
        snapshot = {"messages": {group.channel_id: "老快照的合并版"}, "ledger": empty_ledger("2026-10-10")}
        pushed: list[str] = []
        with patch.object(dz, "load_prepared", return_value=snapshot), patch.object(
            dz, "groups_for_tz", return_value=[group]
        ), patch.object(
            dz, "push_duzhan_message", side_effect=lambda body, channel, idempotency_key="": pushed.append(body) or True
        ):
            result = dz.run_duzhan(
                TZ_SHANGHAI, 20, datetime(2026, 10, 10, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
            )
        self.assertEqual(pushed, ["老快照的合并版"])
        self.assertEqual(result["messages"], 1)


if __name__ == "__main__":
    unittest.main()
