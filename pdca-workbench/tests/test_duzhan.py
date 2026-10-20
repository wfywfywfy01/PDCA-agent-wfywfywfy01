# -*- coding: utf-8 -*-
"""督战官：Lina 用巴黎时间/英文，其余北京时间/中文。"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import unittest

from app import duzhan as duzhan_module
from app.duzhan import (
    TZ_PARIS,
    TZ_SHANGHAI,
    collect_clock,
    cron_timezones,
    draft_at_reply,
    groups_for_tz,
    is_at_duzhan,
    load_prepared,
    parse_hours,
    poll_at_mentions,
    prepare_duzhan,
    render_brief,
    run_duzhan,
    strip_at,
)


def _group(name: str):
    """按群名取群：群清单随业务调整（2026-10-10 新人小组群停推、新增 Q4五百万），
    测试一律按名字取，不用下标 —— 顺序一变，下标就会打到别的群上。"""
    for group in groups_for_tz(TZ_SHANGHAI) + groups_for_tz(TZ_PARIS):
        if group.name == name:
            return group
    raise AssertionError(f"群清单里没有这个群：{name}")


class LongFormatMixin:
    """断言老长版文案时，把精简档位关掉（2026-09-19 起默认精简）。"""

    def setUp(self):
        super().setUp()
        from app.config import get_settings

        settings = get_settings()
        self._compact_backup = getattr(settings, "duzhan_compact", True)
        settings.duzhan_compact = False
        self.addCleanup(self._restore_compact)

    def _restore_compact(self):
        from app.config import get_settings

        get_settings().duzhan_compact = self._compact_backup


class DuzhanGroupTests(LongFormatMixin, unittest.TestCase):
    def test_lina_is_paris_english(self):
        paris = groups_for_tz(TZ_PARIS)
        self.assertEqual([g.name for g in paris], ["Lina业绩达标群"])
        self.assertEqual(paris[0].lang, "en")

    def test_other_groups_are_shanghai_chinese(self):
        shanghai = groups_for_tz(TZ_SHANGHAI)
        names = [g.name for g in shanghai]
        self.assertEqual(
            names,
            [
                "于冰业绩达标群",
                "杨晶晶业绩达标群",
                "viki业绩达标群",
                "Q4五百万",
            ],
        )
        self.assertTrue(all(g.lang == "zh" for g in shanghai))
        q4 = _group("Q4五百万")
        self.assertEqual(q4.channel_id, "b0f2deaf-dea1-463a-98dd-970a1ddd1415")
        self.assertEqual(q4.tz, TZ_SHANGHAI)

    def test_cron_registers_both_timezones(self):
        self.assertEqual(cron_timezones(), [TZ_SHANGHAI, TZ_PARIS])

    def test_parse_hours_default_slots(self):
        self.assertEqual(parse_hours(["10:00", "15:00", "20:00"]), [10, 15, 20])

    def test_collect_runs_before_push(self):
        self.assertEqual(collect_clock(10, 15), (9, 45))
        self.assertEqual(collect_clock(15, 15), (14, 45))
        self.assertEqual(collect_clock(20, 15), (19, 45))
        self.assertEqual(collect_clock(10, 10), (9, 50))

    def test_lina_brief_uses_paris_clock(self):
        group = _group("Lina业绩达标群")
        now = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo(TZ_PARIS))
        text = render_brief(group, 10, now)
        self.assertIn("Paris time", text)
        self.assertIn("10:00", text)
        self.assertIn("Morning chase", text)
        self.assertIn("pending", text)
        self.assertIn("wan", text)
        self.assertIn("Overseas monthly target: 1328 wan CNY", text)
        self.assertIn("No plan posted", text)
        self.assertNotIn("北京", text)
        self.assertNotIn("待确认", text)
        self.assertNotIn("万", text)
        self.assertNotIn("客户A", text)

    def test_lina_ledger_body_is_english(self):
        group = _group("Lina业绩达标群")
        now = datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo(TZ_PARIS))
        ledger = {
            "today_target": "1300万战役",
            "people": [
                {
                    "group": "Lina业绩达标群",
                    "display": "Lina",
                    "target_wan": 400,
                    "mtd_wan": 55,
                    "collections": [
                        {
                            "title": "土耳其合同与伊斯坦布尔市场保护 今天与迪拜经销商讨论了土耳其合同。",
                            "amount": "",
                            "progress": "待确认",
                        }
                    ],
                    "blockers": ["hi Gary关于土耳其合同，他们让我先向你确认并获得你对以下两点的批准，然后再加入合同： 1. 折扣："],
                    "evidence": [],
                    "vemory_ok": False,
                    "mto_count": 4,
                    "mto_names": ["a.jpg"],
                }
            ],
            "red": [{"display": "Lina", "mtd_wan": 55, "reason": "WhatsApp未覆盖"}],
            "black": [{"display": "Safae", "reason": "WhatsApp未覆盖；本月已录单0"}],
            "penalties": [],
        }
        text = render_brief(group, 20, now, ledger)
        self.assertIn("Turkey contract", text)
        self.assertIn("discount", text)
        # 老板 2026-10-10：render_brief 不再追加红榜/黑榜/奖励台账/扣罚台账整块，
        # 英文档同款停发 —— 台账里就算带着 red/black，群里也不再出现。
        self.assertNotIn("Red TOP3", text)
        self.assertNotIn("Black", text)
        self.assertNotIn("Reward ledger", text)
        self.assertNotIn("Penalty ledger", text)
        self.assertNotIn("待确认", text)
        self.assertNotIn("土耳其", text)
        # 英文档里不允许漏出中文：文案映射表（duzhan.py 的 zh→en 映射）与生成端
        # 必须成对改名，否则会像 2026-09-20 的「本月回款0→本月已录单0」那样只改一半。
        leftovers = sorted({ch for ch in text if "\u4e00" <= ch <= "\u9fff"})
        self.assertEqual(leftovers, [], f"英文正文里仍有中文: {leftovers}")
        self.assertNotIn("折扣", text)
        self.assertNotIn("本月回款", text)

    def test_shanghai_brief_uses_beijing_clock(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text = render_brief(group, 10, now)
        self.assertIn("北京时间", text)
        self.assertIn("早追·定任务", text)
        self.assertIn("每日三追进度表", text)
        self.assertIn("待确认", text)
        self.assertIn("本月海外目标：1328万", text)

    def test_midday_and_evening_slot_titles(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        self.assertIn("中追·追变化", render_brief(group, 15, now))
        self.assertIn("晚追·验兑现", render_brief(group, 20, now))

    def test_custom_times_use_nearest_business_stage(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 9, 35, tzinfo=ZoneInfo(TZ_SHANGHAI))
        self.assertIn("早追·定任务", render_brief(group, 9, now, minute=35))
        self.assertIn("中追·追变化", render_brief(group, 14, now, minute=35))
        self.assertIn("晚追·验兑现", render_brief(group, 19, now, minute=35))

    def test_custom_midday_names_actual_previous_slot(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 14, 10, tzinfo=ZoneInfo(TZ_SHANGHAI))
        previous = {"people": []}
        text = render_brief(
            group, 14, now, previous, previous,
            minute=10, previous_slot="09:35",
        )
        self.assertIn("相对 09:35 的变化", text)
        self.assertNotIn("相对 10:00 的变化", text)

    def test_sparse_custom_slots_use_current_state_or_actual_baseline(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 14, 10, tzinfo=ZoneInfo(TZ_SHANGHAI))
        ledger = {"people": [{"group": group.name, "display": "于冰"}]}
        midday = render_brief(
            group, 14, now, ledger, minute=10, previous_slot="",
        )
        self.assertIn("当前状态", midday)
        self.assertNotIn("相对上一档", midday)
        self.assertIn("当前口径；累计已录单", midday)
        self.assertNotIn("本次新增 待确认", midday)

        morning = render_brief(
            group, 9, now, ledger, ledger,
            minute=35, previous_slot="昨日 14:10",
        )
        self.assertIn("昨日 14:10 未闭环", morning)
        self.assertNotIn("昨日未闭环", morning)

    def test_custom_time_reads_the_actual_previous_configured_snapshot(self):
        group = _group("于冰业绩达标群")
        agent = SimpleNamespace(blocks_json=json.dumps({"blocks": [
            {"type": "times", "slots": ["09:35", "14:10", "19:45"]},
        ]}))
        with patch("app.duzhan.load_prepared", return_value={"ledger": {"marker": "previous"}}) as load:
            result = duzhan_module._previous_prepared_for_group(
                TZ_SHANGHAI, "2026-09-17", 14, 10, group.channel_id, [(agent, group)],
            )
        self.assertEqual(result["ledger"]["marker"], "previous")
        load.assert_called_once_with(
            TZ_SHANGHAI, 9, "2026-09-17", group.channel_id[:8], 35,
        )

        with patch("app.duzhan.load_prepared", return_value={}) as load:
            duzhan_module._previous_prepared_for_group(
                TZ_SHANGHAI, "2026-09-17", 9, 35, group.channel_id, [(agent, group)],
            )
        load.assert_any_call(TZ_SHANGHAI, 19, "2026-09-16", group.channel_id[:8], 45)

    def test_weekend_skips_push(self):
        saturday = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        with patch("app.duzhan.push_duzhan_message") as push:
            result = run_duzhan(TZ_SHANGHAI, 10, saturday)
        self.assertEqual(result["sent"], [])
        self.assertEqual(result["skipped"], "weekend")
        push.assert_not_called()

    def test_midday_renders_only_changes(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 16, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = {
            "people": [
                {
                    "group": "于冰业绩达标群",
                    "display": "于冰",
                    "collections": [
                        {"title": "柬埔寨", "progress": "待确认", "status": "planned"},
                        {"title": "越南尾款", "progress": "催收", "status": "progress"},
                        {"title": "马来Derict", "progress": "已询问", "status": "planned"},
                    ],
                }
            ]
        }
        curr = {
            "people": [
                {
                    "group": "于冰业绩达标群",
                    "display": "于冰",
                    "target_wan": 200,
                    "mtd_wan": 170.2,
                    "collections": [
                        {"title": "柬埔寨", "progress": "已到账", "status": "done"},
                        {"title": "越南尾款", "progress": "催收", "status": "progress"},
                    ],
                }
            ]
        }
        text = render_brief(group, 15, now, curr, prev)
        self.assertIn("完成", text)
        self.assertIn("柬埔寨", text)
        self.assertIn("停滞", text)
        self.assertIn("越南尾款", text)
        self.assertIn("未回复", text)
        self.assertIn("马来Derict", text)
        self.assertNotIn("VPS 留痕", text)
        self.assertIn("VPS 留痕", render_brief(group, 10, now, curr))

    def test_missing_snapshot_collects_live_not_empty(self):
        """快照缺失时必须现场补采，不能把整屏“待确认”推给群（2026-09-18 20:00 事故）。"""
        group = _group("于冰业绩达标群")
        ledger = {
            "day": "2026-09-18",
            "today_target": "1300万战役",
            "people": [
                {
                    "group": "于冰业绩达标群",
                    "display": "于冰",
                    "target_wan": 200,
                    "mtd_wan": 170.2,
                    "daily_target_wan": 6.67,
                    "rolling_target_wan": 120.1,
                    "target_gap_wan": 50.1,
                    "target_ahead": True,
                }
            ],
            "red": [],
            "black": [],
        }
        with patch("app.duzhan.load_prepared", return_value=None), patch(
            "app.duzhan.collect_ledger", return_value=ledger
        ) as collect, patch("app.duzhan.push_duzhan_message", return_value=True) as push:
            result = run_duzhan(
                TZ_SHANGHAI,
                20,
                datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI)),
            )
        collect.assert_called_once_with("2026-09-18")
        bodies = {
            call.args[1]: call.args[0] for call in push.call_args_list
        }
        yu_bing = bodies.get("df41ad35-0e26-4431-ac36-10789ff51a1c") or ""
        self.assertTrue(yu_bing, "必须推到于冰群")
        self.assertIn("已录单（开单额）：170.2 万", yu_bing, "兜底采集后必须是真实数字")
        self.assertIn("滚动日目标", yu_bing)
        self.assertFalse(result["from_snapshot"])

    def test_run_duzhan_paris_only_hits_lina(self):
        empty = {"day": "2026-09-15", "people": [], "red": [], "black": []}
        with patch("app.duzhan.push_duzhan_message", return_value=True) as push, patch(
            "app.duzhan.collect_ledger", return_value=empty
        ):
            result = run_duzhan(
                TZ_PARIS,
                10,
                datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo(TZ_PARIS)),
            )
        self.assertEqual(result["sent"], ["Lina业绩达标群"])
        self.assertEqual(len(push.call_args_list), 1)
        body = push.call_args.args[0]
        channel = push.call_args.args[1]
        self.assertIn("Paris time", body)
        self.assertIn("Daily Triple Chase", body)
        self.assertEqual(channel, "e435ab5d-d425-4ccd-a247-c7207efbb4f6")

    def test_prepare_then_push_uses_snapshot(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake_settings = type("S", (), {"data_dir": Path(tmp.name)})()
        now = datetime(2026, 9, 15, 9, 45, tzinfo=ZoneInfo(TZ_PARIS))
        with patch("app.duzhan.get_settings", return_value=fake_settings), patch(
            "app.duzhan.collect_ledger", return_value={"day": "2026-09-15", "people": [], "red": [], "black": [], "today_target": "1300万战役"}
        ):
            prepared = prepare_duzhan(TZ_PARIS, 10, now)
            loaded = load_prepared(TZ_PARIS, 10, "2026-09-15")
        self.assertEqual(prepared["hour"], 10)
        self.assertIn("e435ab5d-d425-4ccd-a247-c7207efbb4f6", prepared["messages"])
        self.assertEqual(loaded["prepared_at"], prepared["prepared_at"])
        with patch("app.duzhan.get_settings", return_value=fake_settings), patch(
            "app.duzhan.push_duzhan_message", return_value=True
        ) as push, patch("app.duzhan.render_brief") as render:
            result = run_duzhan(
                TZ_PARIS,
                10,
                datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo(TZ_PARIS)),
            )
        render.assert_not_called()
        self.assertTrue(result["from_snapshot"])
        self.assertEqual(push.call_args.args[0], prepared["messages"]["e435ab5d-d425-4ccd-a247-c7207efbb4f6"])


class DuzhanPushTests(unittest.TestCase):
    def test_duzhan_push_uses_own_bot_not_daily_report(self):
        from app import vps_im_push

        with patch("app.vps_im_push.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"ok": True}
            with patch.dict(
                "os.environ",
                {
                    "PDCA_DUZHAN_BOT_APP_ID": "vbot_duzhan",
                    "PDCA_DUZHAN_BOT_APP_SECRET": "secret_duzhan",
                    "PDCA_VPS_BOT_APP_ID": "vbot_daily",
                    "PDCA_VPS_BOT_APP_SECRET": "secret_daily",
                },
            ):
                ok = vps_im_push.push_duzhan_message("hi", "chan-lina")
        self.assertTrue(ok)
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["x-vertu-bot-app-id"], "vbot_duzhan")
        self.assertEqual(post.call_args.kwargs["json"]["channel_id"], "chan-lina")
        self.assertNotIn("idempotency_key", post.call_args.kwargs["json"])

    def test_duzhan_push_sends_idempotency_key(self):
        from app import vps_im_push

        with patch("app.vps_im_push.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"ok": True}
            with patch.dict(
                "os.environ",
                {
                    "PDCA_DUZHAN_BOT_APP_ID": "vbot_duzhan",
                    "PDCA_DUZHAN_BOT_APP_SECRET": "secret_duzhan",
                },
            ):
                ok = vps_im_push.push_duzhan_message(
                    "hi",
                    "chan-lina",
                    idempotency_key="duzhan-20260915-1000-x",
                )
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["idempotency_key"], "duzhan-20260915-1000-x")
        self.assertEqual(payload["client_message_id"], "duzhan-20260915-1000-x")
        self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "duzhan-20260915-1000-x")


class DuzhanAtReplyTests(unittest.TestCase):
    def test_only_at_bot_triggers(self):
        self.assertTrue(is_at_duzhan("@海外渠道督战官 who is the president"))
        self.assertTrue(is_at_duzhan("进度如何 ＠海外渠道督战官"))
        self.assertFalse(is_at_duzhan("三角形内角和=？"))
        self.assertFalse(is_at_duzhan("@杨晶晶 同步进度"))

    def test_strip_leaves_the_question(self):
        self.assertEqual(strip_at("@海外渠道督战官 1+1=？"), "1+1=？")

    def test_math_reply(self):
        self.assertEqual(draft_at_reply("2+1=？", "zh"), "3")
        self.assertEqual(draft_at_reply("1+1", "en"), "2")

    def test_empty_at_is_ack(self):
        self.assertEqual(draft_at_reply("", "zh"), "在。")
        self.assertEqual(draft_at_reply("", "en"), "Here.")


    def test_reply_save_keeps_same_cursor_schema(self):
        """2026-09-20 修：逐条落盘的游标曾写成 last_seen/answered，读取端只认
        last_created_at/answered_ids → 下一次轮询会把游标当空的重初始化（漏答 @），
        并丢掉已答 id 集合（重答）。"""
        import json
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        runtime = root / "runtime"
        runtime.mkdir()
        channel = "e435ab5d-d425-4ccd-a247-c7207efbb4f6"
        cursor = runtime / "duzhan_at_cursor.json"
        cursor.write_text(
            json.dumps(
                {"channels": {channel: {"last_created_at": "2026-09-15T07:40:00Z", "answered_ids": []}}}
            ),
            encoding="utf-8",
        )
        fake_settings = type("S", (), {"data_dir": root})()
        first = [
            {
                "id": "q1",
                "created_at": "2026-09-15T07:50:00Z",
                "body": "@海外渠道督战官 1+1=？",
            }
        ]
        later = first + [
            {
                "id": "q2",
                "created_at": "2026-09-15T07:55:00Z",
                "body": "@海外渠道督战官 2+1=？",
            }
        ]
        replies: list[str] = []

        def fake_fetch(channel_id, date_from):
            if channel_id != channel:
                return []
            return list(later if replies else first)

        with patch("app.duzhan.get_settings", return_value=fake_settings), patch(
            "app.duzhan._fetch_recent", side_effect=fake_fetch
        ), patch(
            "app.duzhan.push_duzhan_message", side_effect=lambda body, cid, **kw: replies.append(kw.get("parent_message_id")) or True
        ) as push:
            first_result = poll_at_mentions()
            saved = json.loads(cursor.read_text(encoding="utf-8"))["channels"][channel]
            self.assertIn("last_created_at", saved, "落盘必须沿用读取端的 schema")
            self.assertIn("answered_ids", saved)
            self.assertIn("q1", saved["answered_ids"])
            self.assertEqual(saved["last_created_at"], "2026-09-15T07:50:00Z")
            second_result = poll_at_mentions()

        self.assertEqual(len(first_result["replied"]), 1, first_result)
        self.assertEqual(len(second_result["replied"]), 1, second_result)
        self.assertTrue(second_result["replied"][0].endswith(":q2"), second_result)
        self.assertEqual(replies, ["q1", "q2"], "同一条 @ 只能答一次")
        self.assertEqual(push.call_count, 2)

    def test_answered_ids_keep_insertion_order(self):
        from app.duzhan import _remember_answered

        answered: list[str] = []
        for item in ("b", "a", "c"):
            answered = _remember_answered(answered, item, limit=2)
        self.assertEqual(answered, ["a", "c"], "按写入顺序 FIFO 淘汰，不按字典序")
        self.assertEqual(_remember_answered(answered, "c", limit=2), ["a", "c"], "重复 id 不重复记账")

    def test_first_poll_does_not_answer_history(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake_settings = type("S", (), {"data_dir": Path(tmp.name)})()
        history = [
            {
                "id": "old-at",
                "created_at": "2026-09-15T07:46:56Z",
                "body": "@海外渠道督战官 old question",
            }
        ]
        with patch("app.duzhan.get_settings", return_value=fake_settings), patch(
            "app.duzhan._fetch_recent", return_value=history
        ), patch("app.duzhan.push_duzhan_message") as push:
            result = poll_at_mentions()
        self.assertEqual(len(result["initialized"]), 5)
        push.assert_not_called()

    def test_later_poll_replies_only_new_at(self):
        import json
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        runtime = root / "runtime"
        runtime.mkdir()
        (runtime / "duzhan_at_cursor.json").write_text(
            json.dumps(
                {
                    "channels": {
                        "e435ab5d-d425-4ccd-a247-c7207efbb4f6": {
                            "last_created_at": "2026-09-15T07:40:00Z",
                            "answered_ids": [],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        fake_settings = type("S", (), {"data_dir": root})()

        def fake_fetch(channel_id: str, date_from: str):
            if channel_id != "e435ab5d-d425-4ccd-a247-c7207efbb4f6":
                return []
            return [
                {
                    "id": "noise",
                    "created_at": "2026-09-15T07:50:00Z",
                    "body": "三角形内角和=？",
                },
                {
                    "id": "hit",
                    "created_at": "2026-09-15T07:51:00Z",
                    "body": "@海外渠道督战官 1+1=？",
                },
            ]

        with patch("app.duzhan.get_settings", return_value=fake_settings), patch(
            "app.duzhan._fetch_recent", side_effect=fake_fetch
        ), patch("app.duzhan.push_duzhan_message", return_value=True) as push:
            result = poll_at_mentions()
        self.assertEqual(result["replied"], ["Lina业绩达标群:hit"])
        self.assertEqual(len(push.call_args_list), 1)
        self.assertEqual(push.call_args.kwargs["parent_message_id"], "hit")
        self.assertEqual(push.call_args.args[0], "2")


class DuzhanLedgerTests(LongFormatMixin, unittest.TestCase):
    def test_parse_wa_none_when_not_included(self):
        from app.duzhan_ledger import parse_wa_reached

        value, lower = parse_wa_reached(
            {
                "rows": [
                    {
                        "row_type": "summary",
                        "platform_metrics": {
                            "whatsapp": {"included": False, "reached_customer_count": 0}
                        },
                    }
                ]
            }
        )
        self.assertIsNone(value)
        self.assertFalse(lower)

    def test_parse_wa_lower_bound(self):
        from app.duzhan_ledger import parse_wa_reached

        value, lower = parse_wa_reached(
            {
                "is_complete": False,
                "rows": [
                    {
                        "row_type": "summary",
                        "data_freshness": {"overall_status": "partial"},
                        "platform_metrics": {
                            "whatsapp": {"included": True, "reached_customer_count": 5}
                        },
                    }
                ],
            }
        )
        self.assertEqual(value, 5)
        self.assertTrue(lower)

    def test_red_top3_black_two_to_improve(self):
        from app.duzhan_ledger import PersonRow, rank_red_black, score_row

        people = [
            score_row(PersonRow(
                "于冰业绩达标群",
                "于冰",
                collections=[
                    {"title": "柬埔寨", "status": "done", "amount": "$1"},
                    {"title": "越南", "status": "done"},
                    {"title": "马来", "status": "done"},
                ],
                evidence=["XSD-1"],
            )),
            score_row(PersonRow(
                "viki业绩达标群",
                "Viki",
                collections=[
                    {"title": "伊朗", "status": "done"},
                    {"title": "科威特", "status": "done"},
                ],
            )),
            score_row(PersonRow(
                "杨晶晶业绩达标群",
                "杨晶晶",
                collections=[
                    {"title": "索契", "status": "done"},
                    {"title": "Naya", "status": "progress"},
                ],
            )),
            score_row(PersonRow("Lina业绩达标群", "Lina", collections=[{"title": "迪拜", "status": "planned"}])),
            score_row(PersonRow(
                "新人小组业绩达标群",
                "邓琳莹",
                collections=[{"title": "沉睡老客", "progress": "今天可付款", "status": "planned"}],
            )),
        ]
        red, black = rank_red_black(people)
        self.assertEqual([item["display"] for item in red], ["于冰", "Viki", "杨晶晶"])
        self.assertEqual([item["display"] for item in black], ["邓琳莹", "Lina"])
        self.assertEqual(people[0].score, 110.0)
        self.assertEqual(people[4].score, -10.0)
        self.assertIn("逾期1项", people[4].gaps)
        empty = score_row(PersonRow("新人小组业绩达标群", "Safae", collections=[]))
        self.assertEqual(empty.score, 0.0)
        self.assertIn("未报今日任务", empty.gaps)

    def test_estimate_hours_caps_per_chat(self):
        from app.duzhan_ledger import estimate_hours, hours_text, parse_wa_hour_chats

        chats = parse_wa_hour_chats(
            {
                "rows": [
                    {
                        "row_type": "detail",
                        "outbound_message_count": 40,
                        "inbound_message_count": 40,
                        "last_message_time": "2026-09-16 15:00:00",
                    }
                ]
            }
        )
        est = estimate_hours(chats, {"mto_count": 0, "collections": [], "vemory": [], "vemory_ok": True})
        self.assertEqual(est["minutes"], 25.0)
        self.assertEqual(est["band"], "证据不足")
        self.assertEqual(est["parts"]["gap"], 455.0)

    def test_estimate_hours_near_8h_from_evidence(self):
        from app.duzhan_ledger import estimate_hours, hours_text

        chats = [{"outbound": 10, "inbound": 10, "last": "10:00"}] * 12
        person = {
            "mto_count": 4,
            "mto_quotes": [{"raw_ok": True}] * 4,
            "collections": [{"title": "a"}] * 8,
            "vemory": [
                {"name": "m1", "duration_minutes": 60},
                {"name": "m2", "duration_minutes": 60},
            ],
            "vemory_ok": True,
        }
        est = estimate_hours(chats, person)
        self.assertGreaterEqual(est["hours"], 6.0)
        self.assertLessEqual(est["hours"], 8.0)
        self.assertEqual(est["band"], "近满勤")
        text = hours_text(
            {
                "hours_minutes": est["minutes"],
                "hours_band": est["band"],
                "hours_window": est["window"],
                "hours_parts": est["parts"],
            }
        )
        self.assertIn("标准8h", text)
        self.assertIn("缺口", text)

    def test_mto_hours_cap_half_hour(self):
        from app.duzhan_ledger import estimate_hours

        est = estimate_hours(
            [],
            {
                "mto_count": 8,
                "mto_quotes": [{"raw_ok": True}] * 8,
                "collections": [],
                "vemory": [],
                "vemory_ok": True,
            },
        )
        self.assertEqual(est["parts"]["mto"], 30.0)

    def test_vemory_uses_recorded_duration(self):
        from app.duzhan_ledger import estimate_hours, meeting_minutes

        self.assertEqual(
            meeting_minutes(
                {
                    "start_time": "2026-09-16 10:00:00",
                    "end_time": "2026-09-16 10:45:00",
                }
            ),
            45.0,
        )
        est = estimate_hours(
            [],
            {
                "mto_count": 0,
                "collections": [],
                "vemory": [{"name": "call", "duration_minutes": 45}],
                "vemory_ok": True,
            },
        )
        self.assertEqual(est["parts"]["meeting"], 45.0)
        est_zero = estimate_hours(
            [],
            {
                "mto_count": 0,
                "collections": [],
                "vemory": [{"name": "no-clock"}],
                "vemory_ok": True,
            },
        )
        self.assertEqual(est_zero["parts"]["meeting"], 0.0)
        self.assertEqual(meeting_minutes({"duration_seconds": 2700}), 45.0)
        self.assertEqual(
            meeting_minutes({"start_time": 1789521917265, "end_time": 1789523717265}),
            30.0,
        )
        self.assertEqual(meeting_minutes({"duration_minutes": 450}), 7.5)

    def test_records_to_vemory_rows_uses_participant_owner(self):
        from app.duzhan_ledger import records_to_vemory_rows

        rows = records_to_vemory_rows(
            [
                {
                    "title": "回款会",
                    "external_id": "m1",
                    "duration_minutes": 61,
                    "participants_json": '[{"name": "于冰"}]',
                }
            ]
        )
        self.assertEqual(rows[0]["owner"], "于冰")
        self.assertEqual(rows[0]["duration_minutes"], 61.0)
        skipped = records_to_vemory_rows(
            [
                {
                    "title": "办公室秘书2的快速会议",
                    "external_id": "vps:1dc28dd0-d12c-4f14-8412-6c8186a58f4e",
                    "duration_minutes": 450,
                    "participants_json": '[{"name": "于冰"}]',
                }
            ]
        )
        self.assertEqual(skipped, [])

    def test_estimate_hours_does_not_fill_gap_with_idle_window(self):
        from app.duzhan_ledger import estimate_hours

        est = estimate_hours(
            [{"outbound": 1, "inbound": 0, "last": "09:00"}],
            {"mto_count": 0, "collections": [], "vemory": [], "vemory_ok": True},
        )
        self.assertLess(est["hours"], 1)
        self.assertGreater(est["parts"]["gap"], 400)

    def test_vps_hours_from_weekly_turns(self):
        from app.duzhan_ledger import estimate_hours, vps_minutes, workdays_this_week

        self.assertEqual(workdays_this_week("2026-09-16"), 3)
        self.assertEqual(workdays_this_week("2026-09-14"), 1)
        self.assertEqual(vps_minutes({"vps_turns": 15, "vps_weekdays": 3}), 30.0)
        self.assertEqual(vps_minutes({"vps_turns": 100, "vps_weekdays": 1}), 150.0)
        est = estimate_hours(
            [],
            {
                "mto_count": 0,
                "collections": [],
                "vemory": [],
                "vemory_ok": True,
                "vps_turns": 15,
                "vps_weekdays": 3,
            },
        )
        self.assertEqual(est["parts"]["vps"], 30.0)

    def test_render_fills_ledger_and_evening_board(self):
        """长版台账字段照旧填满；20:00 自 2026-10-10 起不再追加红黑榜板块。"""
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        ledger = {
            "today_target": "1300万战役",
            "people": [
                {
                    "group": "于冰业绩达标群",
                    "display": "于冰",
                    "target_wan": 200,
                    "mtd_wan": 170.2,
                    "wa_reached": 0,
                    "wa_lower_bound": True,
                    "intent_count": 0,
                    "mto_count": 8,
                    "mto_names": ["share-image.webp", "share-image2.webp"],
                    "hours_minutes": 396.0,
                    "hours_band": "近满勤",
                    "hours_window": "09:01–15:40",
                    "hours_parts": {
                        "wa": 180,
                        "mto": 80,
                        "collect": 90,
                        "meeting": 46,
                        "vps": 0,
                        "gap": 84,
                        "std": 480,
                    },
                    "vps_im_sent": 56,
                    "vps_agent_calls": 103,
                    "vps_turns": 2,
                    "vemory_ok": True,
                    "vemory": [
                        {
                            "name": "迪拜 Billionaire 0915",
                            "link": "https://audio/m1.wav",
                        }
                    ],
                    "collections": [
                        {
                            "title": "柬埔寨支付订单 38246$ XSD-DL26091502472",
                            "amount": "$38246",
                            "progress": "待确认",
                        }
                    ],
                    "blockers": ["马来Derict D 已询问未回复"],
                    "evidence": ["XSD-DL26091502472"],
                }
            ],
            "red": [
                {"display": "于冰", "mtd_wan": 170.2, "reason": "过程与回款均有数"},
                {"display": "Viki", "mtd_wan": 147.4, "reason": "今日WhatsApp触达0"},
                {"display": "杨晶晶", "mtd_wan": 86.5, "reason": "今日明确意向0"},
            ],
            "black": [
                {"display": "新人小组", "reason": "本月已录单0"},
                {"display": "Lina", "reason": "WhatsApp未覆盖"},
            ],
            "penalties": [],
        }
        text = render_brief(group, 20, now, ledger)
        self.assertIn("月度目标：200 万", text)
        self.assertIn("已录单（开单额）：170.2 万", text)
        # 当月总目标使用确认文件，不沿用台账中的历史战役口号。
        self.assertIn("战役：本月海外目标：1328万", text)
        self.assertIn("滚动日目标：", text)
        self.assertNotIn("今日目标：1300万战役", text)
        self.assertIn("已交8/4（达标）：share-image.webp、share-image2.webp", text)
        self.assertIn("VPS 留痕：IM发送56条 | Agent轮数2（本周累计，工时按日均×6分钟）", text)
        self.assertIn("WhatsApp 沟通户数：0（已同步下限） 户", text)
        self.assertIn("工时（对照标准8h）：6.6h / 标准8h｜近满勤｜WA 3.0h + MTO 1.33h + 催收跟进 1.5h + 会议 0.77h + VPS 0.0h｜缺口 1.4h；WA窗口 09:01–15:40（跨度≠工时）", text)
        self.assertIn("产生明确意向：0 户", text)
        self.assertIn("Vemory 会议录音：1场 迪拜 Billionaire 0915 https://audio/m1.wav", text)
        self.assertIn("柬埔寨支付订单", text)
        self.assertIn("XSD-DL26091502472", text)
        # 老板 2026-10-10：红榜/黑榜/奖励台账/扣罚台账整块停发 —— 台账里带着
        # red/black/penalties，群里也不再出现部门口径的全员榜。
        self.assertNotIn("红榜", text)
        self.assertNotIn("黑榜", text)
        self.assertNotIn("奖励台账", text)
        self.assertNotIn("扣罚台账", text)
        self.assertNotIn("@于冰", text)
        self.assertNotIn("红榜", render_brief(group, 10, now, ledger))

    def test_parse_mto_skips_bot_and_revoked(self):
        from app.duzhan_ledger import DUZHAN_BOT_ID, parse_mto_images

        count, names = parse_mto_images(
            [
                {
                    "message_type": "image",
                    "sender_bot_id": DUZHAN_BOT_ID,
                    "attachments": [{"attachment_type": "image", "name": "bot.png"}],
                },
                {
                    "message_type": "image",
                    "revoked_at": "2026-09-15T03:00:00Z",
                    "attachments": [{"attachment_type": "image", "name": "gone.png"}],
                },
                {
                    "message_type": "image",
                    "sender_bot_id": None,
                    "attachments": [{"attachment_type": "image", "name": "0915 Agent Q.webp"}],
                },
            ]
        )
        self.assertEqual(count, 1)
        self.assertEqual(names, ["0915 Agent Q.webp"])

    def test_parse_agent_im_current_week(self):
        from app.duzhan_ledger import _vps_for_owner, parse_agent_im_activity
        from app.duzhan_ledger import OWNERS

        html = (
            '<script id="payload" type="application/json">'
            '{"memberRows":['
            '{"period":"current_week","name":"于冰","department":"经销商一部",'
            '"directSent":19,"groupSent":37,"openCodeCalls":101,"harnessCalls":0,"standardTurns":2,'
            '"firstAt":"2026-09-14T02:00:09.172Z","lastAt":"2026-09-15T09:19:34.181Z"},'
            '{"period":"complete_week","name":"于冰","department":"经销商一部",'
            '"directSent":79,"groupSent":219,"openCodeCalls":324,"harnessCalls":0,"standardTurns":0},'
            '{"period":"current_week","name":"王宇彤","department":"海外渠道中台",'
            '"directSent":20,"groupSent":8,"openCodeCalls":0,"harnessCalls":0,"standardTurns":0},'
            '{"period":"current_week","name":"Safae Ben M\'hamed","department":"经销商三部",'
            '"directSent":11,"groupSent":0,"openCodeCalls":0,"harnessCalls":0,"standardTurns":0}'
            "]}</script>"
        )
        rows = parse_agent_im_activity(html, "current_week")
        self.assertEqual(rows["于冰"]["im_sent"], 56)
        self.assertEqual(rows["于冰"]["agent_calls"], 103)
        self.assertEqual(rows["于冰"]["turns"], 103)
        yu = next(item for item in OWNERS if item.display == "于冰")
        wang = next(item for item in OWNERS if item.display == "王宇彤")
        safae = next(item for item in OWNERS if item.display == "Safae")
        self.assertEqual(_vps_for_owner(yu, rows)[:2], (56, 103))
        self.assertEqual(_vps_for_owner(yu, rows)[4], 103)
        self.assertFalse(_vps_for_owner(yu, rows)[5])
        self.assertEqual(_vps_for_owner(wang, rows)[:2], (28, 0))
        self.assertEqual(_vps_for_owner(safae, rows)[:2], (11, 0))

    def test_parse_agent_im_daily_members(self):
        from app.duzhan_ledger import parse_agent_im_activity, vps_minutes

        html = (
            '<script id="payload" type="application/json">'
            '{"members":['
            '{"name":"王宇彤","directSent":7,"groupSent":2,"standardTurns":22,'
            '"openCode":0,"harness":0},'
            '{"name":"于冰","directSent":13,"groupSent":14,"standardTurns":0,'
            '"openCode":32,"harness":0}'
            "]}</script>"
        )
        rows = parse_agent_im_activity(html)
        self.assertTrue(rows["王宇彤"]["daily"])
        self.assertEqual(rows["王宇彤"]["turns"], 22)
        self.assertEqual(rows["于冰"]["im_sent"], 27)
        self.assertEqual(rows["于冰"]["turns"], 32)
        self.assertEqual(vps_minutes({"vps_turns": 22, "vps_weekdays": 1}), 132.0)

    def test_match_vemory_by_owner_aliases(self):
        from app.duzhan_ledger import OWNERS, match_vemory

        rows = [
            {
                "name": "迪拜代理",
                "owner": "于冰",
                "link": "https://audio/m1.wav",
                "id": "m1",
            },
            {
                "name": "科威特跟进",
                "owner": "尤文静",
                "link": "https://audio/m2.wav",
                "id": "m2",
            },
            {
                "name": "新部早会",
                "owner": "王宇彤",
                "link": "",
                "id": "m3",
            },
        ]
        yu = next(item for item in OWNERS if item.display == "于冰")
        viki = next(item for item in OWNERS if item.display == "Viki")
        wang = next(item for item in OWNERS if item.display == "王宇彤")
        lina = next(item for item in OWNERS if item.display == "Lina")
        hits, ok = match_vemory(yu, rows)
        self.assertTrue(ok)
        self.assertEqual([item["name"] for item in hits], ["迪拜代理"])
        self.assertEqual(match_vemory(viki, rows)[0][0]["name"], "科威特跟进")
        self.assertEqual(match_vemory(wang, rows)[0][0]["name"], "新部早会")
        self.assertEqual(match_vemory(lina, rows)[0], [])
        self.assertFalse(match_vemory(yu, None)[1])

    def test_lina_alias_includes_chinese_name(self):
        """老板 2026-09-18 确认：丽娜 = Lina，会议/日报按别名要能对上。"""
        from app.duzhan_ledger import OWNERS, match_daily_report, vemory_aliases

        lina = [item for item in OWNERS if item.display == "Lina"][0]
        self.assertIn("丽娜", vemory_aliases(lina))
        matched = match_daily_report(lina, {"丽娜": {"item_count": 3, "spent_hours": 8}})
        self.assertEqual(matched.get("item_count"), 3)

    def test_xinren_owners_exclude_zhangqian(self):
        """老板 2026-09-18 拍板：加上江旭（Sana）；吴楠、杨成凤、张倩不加。

        老板 2026-10-10 拍板：新人小组群停推，5 个人按「谁追谁」分流到各组长群与
        Q4五百万 —— 新人小组群名下不再挂人。
        """
        from app.duzhan_ledger import OWNERS

        by_group: dict[str, list[str]] = {}
        for item in OWNERS:
            by_group.setdefault(item.group, []).append(item.display)
        self.assertEqual(
            by_group,
            {
                "于冰业绩达标群": ["于冰"],
                "杨晶晶业绩达标群": ["杨晶晶", "何海文", "王宇彤"],
                "viki业绩达标群": ["Viki", "江旭", "张月馨"],
                "Lina业绩达标群": ["Lina", "Safae"],
                "Q4五百万": ["刘春梅", "邓琳莹"],
            },
        )
        self.assertNotIn("新人小组业绩达标群", by_group, "新人小组群不再有任何成员")
        displays = [item.display for item in OWNERS]
        jiangxu = [item for item in OWNERS if item.display == "江旭"][0]
        self.assertEqual(jiangxu.employee_id, 388)
        self.assertEqual(jiangxu.im_user_id, 14549)
        self.assertIsNone(jiangxu.target_wan, "小组目标是群口径，不摊到个人")
        self.assertEqual(
            jiangxu.follow_channel_id,
            "d038caa8-3bd3-432b-b91a-9bf58180e855",
            "江旭（Sana）要带上 Sana客户跟进群",
        )
        for name in ("吴楠", "杨成凤", "张倩"):
            self.assertNotIn(name, displays, name + " 按老板口径不纳入")
        by_target = {item.display: item.target_wan for item in OWNERS}
        self.assertEqual(by_target["于冰"], 200)
        self.assertEqual(by_target["杨晶晶"], 333)
        self.assertEqual(by_target["何海文"], 95)
        self.assertEqual(by_target["Viki"], 100)
        self.assertEqual(by_target["Lina"], 400)
        self.assertIsNone(by_target["邓琳莹"])
        self.assertNotIn("张倩", displays)
        self.assertNotIn("李浩然", displays)
        self.assertNotIn("邢哲夫", displays)
        self.assertNotIn("陈鹏飞", displays)
        follow = {item.display: item.follow_channel_id for item in OWNERS}
        self.assertEqual(follow["邓琳莹"], "8bb5ae97-3ffb-42e7-869d-c5cef358510a")
        self.assertEqual(follow["Safae"], "8cf4b40b-0e60-4819-9120-a22f3c808a00")
        self.assertEqual(follow["王宇彤"], "792c8c09-4c4f-4162-b0cb-45f6d009b504")
        self.assertEqual(follow["张月馨"], "743227fa-07cc-4bfd-be74-9242aaa56e71")
        ids = {item.display: item.im_user_id for item in OWNERS}
        self.assertEqual(ids["邓琳莹"], 14247)
        self.assertEqual(ids["张月馨"], 14660)

    def test_parse_follow_group_outreach_evidence(self):
        from app.duzhan_ledger import parse_owner_reports

        collections, blockers, evidence = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 14247,
                    "created_at": "2026-09-16T11:08:17Z",
                    "body": "客户名单地区德国，今日触达15人，添加WhatsApp7人，邮箱触达8人其中5封退信，有效触达共计10人，暂无回复",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 14247,
                    "created_at": "2026-09-16T11:57:42Z",
                    "body": "【金山文档 | WPS云文档】 客户跟进台账 https://www.kdocs.cn/l/cct0uNIdy2iO",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 14460,
                    "created_at": "2026-09-16T10:01:41Z",
                    "body": "Contacted 15 customers from the provided list. 7 emails were returned/undelivered.",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 14344,
                    "created_at": "2026-09-16T12:23:27Z",
                    "body": "已填写",
                },
                {
                    "message_type": "link",
                    "sender_user_id": 14660,
                    "created_at": "2026-09-16T10:58:43Z",
                    "body": "https://my.feishu.cn/wiki/TOU3wNUjOiZtzzkmD9ZceBafnPh?table=tblvH9RLYFbLpDiR",
                },
            ],
            14247,
        )
        self.assertTrue(any("今日触达15人" in item["title"] for item in collections))
        self.assertTrue(any("暂无回复" in item or "退信" in item for item in blockers))
        self.assertTrue(any("kdocs.cn" in item for item in evidence))
        safae, _, safae_ev = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 14460,
                    "created_at": "2026-09-16T10:01:41Z",
                    "body": "Contacted 15 customers from the provided list. 7 emails were returned/undelivered.",
                }
            ],
            14460,
        )
        self.assertTrue(any("Contacted 15" in item["title"] for item in safae))
        self.assertTrue(any("Contacted 15" in item for item in safae_ev))
        _, _, wang_ev = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 14344,
                    "created_at": "2026-09-16T12:23:27Z",
                    "body": "已填写",
                }
            ],
            14344,
        )
        self.assertIn("跟进表已填写", wang_ev)
        _, _, yue_ev = parse_owner_reports(
            [
                {
                    "message_type": "link",
                    "sender_user_id": 14660,
                    "created_at": "2026-09-16T10:58:43Z",
                    "body": "https://my.feishu.cn/wiki/TOU3wNUjOiZtzzkmD9ZceBafnPh?table=tblvH9RLYFbLpDiR",
                }
            ],
            14660,
        )
        self.assertTrue(any("feishu.cn" in item for item in yue_ev))

    def test_messages_on_day_uses_group_timezone(self):
        from app.duzhan_ledger import messages_on_day

        messages = [
            {"created_at": "2026-09-15T15:59:59Z", "id": "old"},
            {"created_at": "2026-09-15T16:00:00Z", "id": "today"},
        ]
        rows = messages_on_day(messages, "2026-09-16", "Asia/Shanghai")
        self.assertEqual([item["id"] for item in rows], ["today"])

    def test_parse_daily_report_card(self):
        from app.duzhan_ledger import parse_daily_reports

        rows = parse_daily_reports(
            [
                {
                    "created_at": "2026-09-16T12:41:19Z",
                    "metadata": {
                        "kind": "daily_report_submission",
                        "work_date": "2026-09-16",
                        "submitter_name": "尤文静",
                        "today": [
                            {"progress": 100, "spent_hours": 1.5},
                            {"progress": 50, "spent_hours": 3},
                        ],
                    },
                }
            ],
            "2026-09-16",
        )
        self.assertEqual(rows["尤文静"]["item_count"], 2)
        self.assertEqual(rows["尤文静"]["done_count"], 1)
        self.assertEqual(rows["尤文静"]["spent_hours"], 4.5)

    def test_parse_owner_reports_from_group_text(self):
        from app.duzhan_ledger import parse_owner_reports

        collections, blockers, evidence = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:22:09Z",
                    "body": "1.柬埔寨新订单30000$ 2.越南9620$补款",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T11:48:14Z",
                    "body": (
                        "1. 柬埔寨支付订单  38246$  XSD-DL26091502472\n"
                        "2. 越南激活 11台手机，催收尾款\n"
                        "3.马来Derict D 已询问未回复"
                    ),
                }
            ],
            13063,
        )
        titles = [item["title"] for item in collections]
        self.assertTrue(any("9620" in title for title in titles))
        paid = next(item for item in collections if "38246" in (item.get("amount") or "") or "38246" in item["title"])
        self.assertEqual(paid["amount"], "$38246")
        self.assertIn("XSD-DL26091502472", evidence)
        self.assertTrue(any("未回复" in item for item in blockers))
        stalled = next(item for item in collections if "马来" in item["title"])
        self.assertEqual(stalled["status"], "stalled")
        self.assertIn("XSD-DL26091502472", paid.get("evidence") or evidence)

    def test_parse_owner_reports_latest_status_wins_for_same_item(self):
        from app.duzhan_ledger import parse_owner_reports

        collections, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. 待跟进客户A付款，今天完成",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 已完成客户A付款，水单已回传",
                },
            ],
            13063,
        )

        matching = [item for item in collections if "客户A付款" in item["title"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "done")

    def test_parse_owner_reports_keeps_latest_twelve_updates(self):
        from app.duzhan_ledger import parse_owner_reports

        initial = "\n".join(
            f"{index}. 客户{index:02d}付款事项等待确认"
            for index in range(1, 14)
        )
        collections, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": initial,
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 已完成客户01付款事项等待确认，水单已回传",
                },
            ],
            13063,
        )

        titles = [item["title"] for item in collections]
        self.assertEqual(len(titles), 12)
        self.assertTrue(any("客户01" in title for title in titles))
        self.assertFalse(any("客户02" in title for title in titles))
        self.assertEqual(collections[-1]["status"], "done")

    def test_parse_owner_reports_understands_english_completion(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports, task_key

        collections, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. pending Customer Alpha contract follow up",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. completed Customer Alpha contract follow up",
                },
            ],
            13063,
        )

        self.assertEqual(len(collections), 1)
        self.assertEqual(collections[0]["status"], "done")
        for title in (
            "Customer Beta remains unpaid",
            "Customer Alpha has not paid",
            "Customer Beta is not done",
            "Payment is not completed",
            "Customer Gamma is not yet complete",
            "Customer Delta has never paid",
            "Customer Epsilon is no longer complete",
            "Customer Zeta has not been paid",
            "Customer Eta is not fully paid",
            "Payment has not been completed",
            "Customer Theta is yet to be completed",
            "Payment could not have been completed",
            "Payment couldn't have been completed",
            "Payment may not have been completed",
            "Customer Iota payment has not been received",
            "Payment is not currently paid",
            "Payment hasn't currently been paid",
            "Payment was not already paid yesterday",
            "Payment not already paid before shipment",
            "Payment may never have been paid",
            "Payment could never have been paid",
            "Payment never has been paid",
            "Payment could not possibly have been completed",
            "Payment should not have actually been paid",
            "Payment could not ever have been paid",
            "尚未确认客户A已付款",
            "No evidence that Customer A has paid",
            "It is unclear whether payment has been received",
            "Payment has never previously been paid",
            "Payment has never once been paid",
            "Payment is not confirmed paid",
            "Payment was not reported as paid",
        ):
            self.assertEqual(infer_status({"title": title}), "stalled")
        for unfinished, finished in (
            ("Customer Zeta has not paid", "Customer Zeta has paid"),
            ("Customer Eta is not done", "Customer Eta is done"),
            ("Payment was not completed", "Payment was completed"),
            ("Customer Iota has not been paid", "Customer Iota paid"),
            ("Customer Kappa is not fully paid", "Customer Kappa paid"),
            ("Customer Lambda is yet to be completed", "Customer Lambda completed"),
            ("Customer Mu remains unpaid", "Customer Mu paid"),
        ):
            self.assertEqual(task_key({"title": unfinished}), task_key({"title": finished}))
        updated, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. Customer Mu remains unpaid",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. Customer Mu paid",
                },
            ],
            13063,
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["status"], "done")
        unpaid = {"title": "Customer Mu remains unpaid"}
        paid = {"title": "Customer Mu paid"}
        changes = diff_tasks([paid], [unpaid])
        self.assertEqual(changes["completed"], [paid])
        self.assertEqual(changes["new"], [])
        self.assertEqual(changes["unanswered"], [])

    def test_infer_status_requires_explicit_english_completion(self):
        from app.duzhan_ledger import diff_tasks, infer_status, task_key

        for title in (
            "Complete distributor contract tomorrow",
            "Complete customer profile today",
            "Paid media campaign proposal",
            "Today paid media campaign proposal",
            "Today paid-media campaign proposal",
            "Customer Alpha will be completed tomorrow",
            "Customer Alpha is scheduled to be completed",
            "Payment is expected to be paid this week",
            "Order needs to be completed",
            "Balance to be paid tomorrow",
            "Task remains to be completed",
            "Payment should have been paid",
            "Payment may have been paid",
            "Payment should already have been paid",
            "Payment might have already been received",
            "Payment may possibly have been paid",
            "Payment may well have been paid",
            "Payment should perhaps have been paid",
            "Payment is expected to have been paid",
            "Payment was supposed to have been paid",
            "Payment would have been paid",
            "Payment should be received tomorrow but is now paid",
            "Customer Alpha contract will be reviewed by legal but completed tomorrow",
            "Customer Alpha contract will be reviewed by legal but completed on Friday",
            "Customer Alpha contract will be reviewed by legal but completed on 2026-10-16",
            "Customer Alpha contract will be reviewed by legal but completed at 17:00",
            "Payment is to be fully paid tomorrow",
            "Payment is to be completely paid next week",
            "预计明天到账，客户A今天已付款",
        ):
            self.assertEqual(infer_status({"title": title}), "planned")
        for title in (
            "Completed Customer Alpha contract follow up",
            "Customer Alpha contract is complete",
            "Customer Alpha payment is done",
            "Customer Alpha has paid",
            "Customer Alpha has been paid",
            "Customer Alpha paid today",
            "Customer Alpha paid USD 10,000 today",
            "Done: Customer Alpha contract",
            "Done Customer Alpha contract",
            "Paid: Customer Alpha invoice",
            "Paid Customer Alpha invoice",
            "Customer Alpha payment has now been received",
            "Customer Alpha payment is now received",
            "Customer Will is now paid",
            "Customer May has paid invoice",
            "Payment was not only paid but also received",
            "Payment was not just paid but also received",
            "Payment was not merely paid but also received",
            "Customer Alpha paid invoice",
            "Invoice paid by Customer Alpha",
            "customer may has paid invoice",
            "customer will is now paid",
            "Customer Alpha Trading paid invoice",
            "Customer ACME Corp paid invoice",
            "Customer Van Dyke paid invoice",
            "Payment was not only planned but completed",
            "Payment was scheduled but is complete",
            "Customer paid invoice",
            "Customer paid invoice today",
            "Payment was partially paid but is fully paid",
            "Payment was 50% paid but is 100% paid",
            "客户A尾款部分付款后已全部付款",
            "Contract was planned but completed on time",
            "Payment was scheduled but paid on time",
            "Payment was scheduled but completed on 2026-10-10",
            "Payment was scheduled but completed at 17:00",
        ):
            self.assertEqual(infer_status({"title": title}), "done")
        for unfinished, finished in (
            ("Payment will be completed tomorrow", "Payment completed"),
            ("Payment should be completed tomorrow", "Payment completed"),
            ("Payment is expected to be paid this week", "Payment paid"),
            ("Order needs to be completed", "Order completed"),
            ("Balance to be paid tomorrow", "Balance paid"),
            ("Task remains to be completed", "Task completed"),
            ("Payment unpaid", "Payment was not only paid but also received"),
            ("Payment unpaid", "Payment was not just paid but also received"),
            ("Payment unpaid", "Payment was not merely paid but also received"),
            ("Customer Alpha invoice unpaid", "Customer Alpha paid invoice"),
            ("Customer Will unpaid", "Customer Will is now paid"),
            ("Customer May invoice unpaid", "Customer May has paid invoice"),
            ("customer may invoice unpaid", "customer may has paid invoice"),
            ("Customer Alpha Trading invoice unpaid", "Customer Alpha Trading paid invoice"),
            ("Customer ACME Corp invoice unpaid", "Customer ACME Corp paid invoice"),
            ("Customer Van Dyke invoice unpaid", "Customer Van Dyke paid invoice"),
            ("Payment not completed", "Payment was not only planned but completed"),
            ("Payment not completed", "Payment was scheduled but is complete"),
            ("Customer invoice unpaid", "Customer paid invoice"),
            ("Customer invoice unpaid", "Customer paid invoice today"),
            ("Payment unpaid", "Payment was partially paid but is fully paid"),
            ("Payment unpaid", "Payment was 50% paid but is 100% paid"),
            ("客户A尾款未付款", "客户A尾款部分付款后已全部付款"),
            ("Contract not completed", "Contract was planned but completed on time"),
            ("Payment unpaid", "Payment was scheduled but paid on time"),
            (
                "Customer Alpha contract to be completed on Friday",
                "Customer Alpha contract completed",
            ),
            (
                "Customer Alpha contract to be completed on 2026-10-16",
                "Customer Alpha contract completed",
            ),
            (
                "Customer Alpha contract to be completed at 17:00",
                "Customer Alpha contract completed",
            ),
        ):
            self.assertEqual(task_key({"title": unfinished}), task_key({"title": finished}))
            current = {"title": finished}
            changes = diff_tasks([current], [{"title": unfinished}])
            self.assertEqual(changes["completed"], [current])
            self.assertEqual(changes["new"], [])
            self.assertEqual(changes["unanswered"], [])

        self.assertNotEqual(
            task_key({"title": "customer may invoice unpaid"}),
            task_key({"title": "customer will invoice unpaid"}),
        )
        automotive_before = {"title": "汽车后市场合同未完成"}
        automotive_after = {"title": "汽车市场合同已完成"}
        self.assertNotEqual(task_key(automotive_before), task_key(automotive_after))
        automotive_changes = diff_tasks([automotive_after], [automotive_before])
        self.assertEqual(automotive_changes["new"], [automotive_after])
        self.assertEqual(automotive_changes["unanswered"], [automotive_before])
        queen_before = {"title": "客户王后订单尾款尚未付款"}
        wang_before = {"title": "客户王订单尾款尚未付款"}
        self.assertNotEqual(task_key(queen_before), task_key(wang_before))
        distinct_names = diff_tasks([wang_before], [queen_before])
        self.assertEqual(distinct_names["new"], [wang_before])
        self.assertEqual(distinct_names["unanswered"], [queen_before])

    def test_infer_status_understands_stalled_english_progress(self):
        from app.duzhan_ledger import diff_tasks, infer_status, task_key

        for title in (
            "Customer Nu no progress",
            "Customer Nu has made no progress",
            "Customer Nu not in progress",
            "Customer Nu has not progressed",
            "Customer Nu has no further progress",
        ):
            self.assertEqual(infer_status({"title": title}), "stalled")
            self.assertEqual(
                task_key({"title": title}),
                task_key({"title": "Customer Nu completed"}),
            )
        stalled = {"title": "Customer Nu has made no progress"}
        done = {"title": "Customer Nu completed"}
        changes = diff_tasks([done], [stalled])
        self.assertEqual(changes["completed"], [done])
        self.assertEqual(changes["new"], [])
        self.assertEqual(changes["unanswered"], [])

    def test_parse_owner_reports_merges_new_completion_evidence(self):
        from app.duzhan_ledger import diff_tasks, parse_owner_reports, task_key

        collections, _, evidence = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. 待跟进客户A付款，今天完成",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 已完成客户A付款，水单已回传 XSD-DL26091502472",
                },
            ],
            13063,
        )

        self.assertEqual(len(collections), 1)
        self.assertEqual(collections[0]["status"], "done")
        self.assertIn("XSD-DL26091502472", collections[0]["evidence"])
        self.assertIn("XSD-DL26091502472", evidence)
        previous = {"title": "待跟进客户A付款，今天完成"}
        current = {"title": "已完成客户A付款，水单已回传 XSD-DL26091502472"}
        changes = diff_tasks([current], [previous])
        self.assertEqual(changes["completed"], [current])
        self.assertEqual(changes["new"], [])
        self.assertEqual(changes["unanswered"], [])

        paid, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. pending Customer Alpha invoice",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. Customer Alpha invoice paid USD 10,000 today",
                },
            ],
            13063,
        )
        self.assertEqual(len(paid), 1)
        self.assertEqual(paid[0]["status"], "done")

        reordered_amount, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. Customer Beta invoice USD 10,000 unpaid",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. Customer Beta invoice 10,000 USD paid",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T10:00:00Z",
                    "body": "1. Customer Beta invoice $10,000 paid",
                },
            ],
            13063,
        )
        self.assertEqual(len(reordered_amount), 1)
        self.assertEqual(reordered_amount[0]["status"], "done")

        for before, after in (
            ("Customer Gamma invoice RMB 10万 unpaid", "Customer Gamma invoice 10万 RMB paid"),
            ("Customer Delta invoice USD 10W unpaid", "Customer Delta invoice 10W USD paid"),
        ):
            scaled_amount, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-09-15T01:00:00Z",
                        "body": f"1. {before}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-09-15T09:00:00Z",
                        "body": f"1. {after}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(scaled_amount), 1)
            self.assertEqual(scaled_amount[0]["status"], "done")

        separate, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": (
                        "1. Customer Alpha invoice XSD-ONE USD 10,000 unpaid\n"
                        "2. Customer Alpha invoice XSD-TWO USD 10,000 unpaid"
                    ),
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. Customer Alpha invoice XSD-ONE USD 10,000 paid",
                },
            ],
            13063,
        )
        self.assertEqual(len(separate), 2)
        self.assertNotEqual(task_key(separate[0]), task_key(separate[1]))
        self.assertEqual(sorted(item["status"] for item in separate), ["done", "stalled"])

        status_word_orders, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": (
                        "1. Customer Alpha invoice XSD-PAID-123 unpaid\n"
                        "2. Customer Alpha invoice XSD-123 unpaid"
                    ),
                }
            ],
            13063,
        )
        self.assertEqual(len(status_word_orders), 2)
        self.assertNotEqual(task_key(status_word_orders[0]), task_key(status_word_orders[1]))

        named_customers, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": (
                        "1. Customer Will invoice unpaid\n"
                        "2. Customer May invoice unpaid\n"
                        "3. Customer Paid invoice unpaid"
                    ),
                }
            ],
            13063,
        )
        self.assertEqual(len(named_customers), 3)
        self.assertNotEqual(task_key(named_customers[0]), task_key(named_customers[1]))
        self.assertNotEqual(task_key(named_customers[1]), task_key(named_customers[2]))

    def test_partial_completion_remains_open(self):
        from app.duzhan_ledger import infer_status, parse_owner_reports, task_key

        for title, finished in (
            ("Customer Alpha contract 50% completed", "Customer Alpha contract completed"),
            ("Customer Alpha contract partially completed", "Customer Alpha contract completed"),
            ("Customer Alpha contract almost complete", "Customer Alpha contract completed"),
            ("Customer Alpha contract mostly completed", "Customer Alpha contract completed"),
            ("Customer Alpha invoice partially paid", "Customer Alpha invoice paid"),
            ("客户A合同已完成50%", "客户A合同已完成"),
            ("客户A合同部分完成", "客户A合同已完成"),
            ("客户A合同已完成一半", "客户A合同已完成"),
            ("客户A合同基本完成", "客户A合同已完成"),
        ):
            self.assertEqual(infer_status({"title": title}), "progress")
            self.assertEqual(
                task_key({"title": title}),
                task_key({"title": finished}),
            )
        self.assertEqual(
            infer_status({"title": "Customer Alpha contract 100% completed"}),
            "done",
        )
        self.assertEqual(
            infer_status({"title": "Customer Alpha payment not 100% completed"}),
            "stalled",
        )
        for title in (
            "Payment will be partially paid tomorrow",
            "Contract is expected to be 50% completed this week",
            "计划完成50%客户A合同",
            "预计客户A尾款部分付款",
            "明天完成50%客户A合同",
        ):
            self.assertEqual(infer_status({"title": title}), "planned")
        partial, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 客户A合同已完成50%",
                }
            ],
            13063,
        )
        self.assertEqual(partial[0]["status"], "progress")
        self.assertEqual(partial[0]["progress"], "部分完成")
        future, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. Payment will be partially paid tomorrow",
                }
            ],
            13063,
        )
        self.assertEqual(future[0]["status"], "planned")
        self.assertEqual(future[0]["progress"], "待确认")

        chinese_future, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 明天完成50%客户A合同",
                }
            ],
            13063,
        )
        self.assertEqual(chinese_future[0]["status"], "planned")
        self.assertEqual(chinese_future[0]["progress"], "待确认")

    def test_chinese_negative_completion_remains_open_and_merges(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports, task_key

        for unfinished, finished in (
            ("客户A尾款未付款", "客户A尾款已付款"),
            ("客户A尾款未支付", "客户A尾款已支付"),
            ("客户A合同未完成", "客户A合同已完成"),
            ("客户A尾款未到账", "客户A尾款已到账"),
        ):
            self.assertEqual(infer_status({"title": unfinished}), "stalled")
            self.assertEqual(task_key({"title": unfinished}), task_key({"title": finished}))
            current = {"title": finished}
            changes = diff_tasks([current], [{"title": unfinished}])
            self.assertEqual(changes["completed"], [current])
            self.assertEqual(changes["new"], [])
            self.assertEqual(changes["unanswered"], [])

        collections, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. 客户A尾款未付款，需要确认",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 客户A尾款已付款，需要确认",
                },
            ],
            13063,
        )
        self.assertEqual(len(collections), 1)
        self.assertEqual(collections[0]["status"], "stalled")
        self.assertEqual(collections[0]["progress"], "未确认")

    def test_current_completion_overrides_historical_negative_state(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports, task_key

        for title in (
            "客户A昨日未付款，今日已付款",
            "客户A今天已付款，昨天未付款",
            "Customer A was unpaid but is now paid",
            "Customer A is now paid; it was unpaid yesterday",
            "Customer A is now paid; it was unpaid as of yesterday",
            "Customer A is now paid; it was unpaid until yesterday",
            "Customer A is now paid; it was unpaid through yesterday",
            "Payment was expected to be paid yesterday but is now paid",
            "客户A原计划昨日付款，今日已付款",
            "Customer A was unpaid but is now paid 100%",
            "Payment was 50% paid yesterday; it is now 100% paid",
            "Payment was partially paid yesterday but is now fully paid",
            "此前尚未确认客户A已付款，现已到账",
            "No evidence that payment was paid yesterday; payment is now received",
            "客户A已经付款",
            "客户A刚完成",
        ):
            self.assertEqual(infer_status({"title": title}), "done")
        for title in (
            "客户A今日已付款，但尚未到账",
            "客户A尾款尚未到账，今天已付款",
            "Customer A is not already paid",
            "Payment could not be completed",
            "Payment cannot be completed",
            "Payment couldn't be completed",
        ):
            self.assertEqual(infer_status({"title": title}), "stalled")
        self.assertEqual(
            infer_status({"title": "客户A尚未付款，今天付款"}),
            "planned",
        )
        for title in (
            "Customer A was unpaid but is now partially paid",
            "客户A昨日未付款，今日部分付款",
            "Customer A was unpaid but is now paid 50%",
            "Customer A invoice 50% has now been paid",
            "Payment was unpaid yesterday but is now received 50%",
            "Payment is now paid only 50%",
            "Payment has now been received only 50%",
            "客户A今天已付款约50%",
            "Payment 50% has been paid",
            "50% of payment has now been paid",
            "Payment has partially been paid",
            "Payment is received 50%",
            "客户A尾款已到账50%",
            "Payment is partially received",
            "客户A尾款部分到账",
        ):
            self.assertEqual(infer_status({"title": title}), "progress")

        for unfinished, progressing in (
            ("Customer A invoice unpaid", "Customer A invoice was unpaid but is now partially paid"),
            ("客户A尾款未付款", "客户A尾款昨日未付款，今日部分付款"),
            ("Customer A invoice unpaid", "Customer A invoice was unpaid but is now paid 50%"),
            ("Customer A invoice unpaid", "Customer A invoice 50% has now been paid"),
            ("Payment unpaid", "Payment was unpaid yesterday but is now received 50%"),
            ("Payment unpaid", "Payment 50% has been paid"),
            ("Payment unpaid", "50% of payment has now been paid"),
            ("Payment unpaid", "Payment has partially been paid"),
            ("Payment unreceived", "Payment is received 50%"),
            ("客户A尾款未到账", "客户A尾款已到账50%"),
            ("Payment unreceived", "Payment is partially received"),
            ("客户A尾款未到账", "客户A尾款部分到账"),
            ("Payment unpaid", "Payment is now paid only 50%"),
            ("Payment unpaid", "Payment is now paid about 50%"),
            ("Payment unpaid", "Payment is now paid roughly 50%"),
            ("客户A未付款", "客户A今天已付款约50%"),
        ):
            self.assertEqual(task_key({"title": unfinished}), task_key({"title": progressing}))
            current = {"title": progressing}
            changes = diff_tasks([current], [{"title": unfinished}])
            self.assertEqual(changes["progressed"], [current])
            self.assertEqual(changes["new"], [])
            self.assertEqual(changes["unanswered"], [])

        for unfinished, finished in (
            ("Customer A invoice unpaid", "Customer A invoice now paid"),
            ("客户Alpha尾款未付款", "客户Alpha尾款现已付款"),
            ("Customer A invoice unpaid", "Customer A invoice was unpaid but is now paid"),
            ("Customer A unpaid", "Customer A is now paid; it was unpaid yesterday"),
            ("Customer A unpaid", "Customer A is now paid; it was unpaid as of yesterday"),
            ("Customer A unpaid", "Customer A is now paid; it was unpaid until yesterday"),
            ("Customer A unpaid", "Customer A is now paid; it was unpaid through yesterday"),
            (
                "Customer A payment has not been received",
                "Customer A payment has now been received",
            ),
            (
                "Payment unpaid",
                "Payment was 50% paid yesterday; it is now 100% paid",
            ),
            (
                "Payment not received",
                "No evidence that payment was paid yesterday; payment is now received",
            ),
            (
                "Customer Alpha payment has not been received",
                "No evidence that Customer Alpha payment was received yesterday; "
                "Customer Alpha payment is now received",
            ),
            (
                "客户A尾款未付款，需要确认",
                "此前尚未确认客户A尾款已付款，现已到账",
            ),
        ):
            self.assertEqual(task_key({"title": unfinished}), task_key({"title": finished}))
            current = {"title": finished}
            changes = diff_tasks([current], [{"title": unfinished}])
            self.assertEqual(changes["completed"], [current])
            self.assertEqual(changes["new"], [])
            self.assertEqual(changes["unanswered"], [])

        amount_before = {"title": "Customer B invoice USD 10 waiting approval unpaid"}
        amount_after = {"title": "Customer B invoice 10 USD waiting approval paid"}
        amount_changes = diff_tasks([amount_after], [amount_before])
        self.assertEqual(amount_changes["completed"], [amount_after])
        self.assertEqual(amount_changes["new"], [])
        self.assertEqual(amount_changes["unanswered"], [])

        for before, after in (
            ("Customer A follow up in 2 weeks", "Customer A follow up in 3 weeks"),
            ("Customer A follow up in 2 working days", "Customer A follow up in 3 working days"),
        ):
            self.assertEqual(task_key({"title": before}), task_key({"title": after}))
            deadline_changes = diff_tasks([{"title": after}], [{"title": before}])
            self.assertEqual(deadline_changes["new"], [])
            self.assertEqual(deadline_changes["unanswered"], [])

        planned_customer = {"title": "Customer will be paid tomorrow"}
        finished_customer = {"title": "Customer paid"}
        self.assertEqual(task_key(planned_customer), task_key(finished_customer))
        customer_changes = diff_tasks([finished_customer], [planned_customer])
        self.assertEqual(customer_changes["completed"], [finished_customer])
        self.assertEqual(customer_changes["new"], [])
        self.assertEqual(customer_changes["unanswered"], [])

        for before, after in (
            ("Customer invoice unpaid", "Customer has paid invoice"),
            ("Customer contract unpaid", "Customer completed contract"),
            ("Customer Alpha follow up", "Customer Alpha will follow up"),
            ("Customer Alpha follow up", "Customer Alpha should follow up"),
            ("Customer Alpha follow up", "Customer Alpha may follow up"),
        ):
            self.assertEqual(task_key({"title": before}), task_key({"title": after}))

        collections, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T01:00:00Z",
                    "body": "1. 客户A尾款未付款，需要确认",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-09-15T09:00:00Z",
                    "body": "1. 客户A尾款昨日未付款，今日已付款，需要确认",
                }
            ],
            13063,
        )
        self.assertEqual(len(collections), 1)
        self.assertEqual(collections[0]["status"], "stalled")
        self.assertEqual(collections[0]["progress"], "未确认")

        for title, expected_progress in (
            ("Payment was not only paid but also received", "已到账"),
            ("Payment was 50% paid yesterday; it is now 100% paid", "已付款"),
            ("Customer May has paid invoice", "已付款"),
            ("Customer Will is now paid", "已付款"),
            ("Customer paid invoice today", "已付款"),
            ("Payment was partially paid but is fully paid", "已付款"),
            ("Payment was 50% paid but is 100% paid", "已付款"),
            ("客户A尾款部分付款后已全部付款", "已付款"),
            (
                "No evidence that payment was paid yesterday; payment is now received",
                "已到账",
            ),
        ):
            parsed, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-09-15T09:00:00Z",
                        "body": f"1. {title}",
                    }
                ],
                13063,
            )
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["status"], "done")
            self.assertEqual(parsed[0]["progress"], expected_progress)

        for previous, current, expected_progress in (
            (
                "Customer Alpha payment has not been received",
                "No evidence that Customer Alpha payment was received yesterday; "
                "Customer Alpha payment is now received",
                "已到账",
            ),
            (
                "客户A尾款未付款，需要确认",
                "此前尚未确认客户A尾款已付款，现已到账",
                "已到账",
            ),
        ):
            parsed, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-09-15T01:00:00Z",
                        "body": f"1. {previous}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-09-15T09:00:00Z",
                        "body": f"1. {current}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["status"], "done")
            self.assertEqual(parsed[0]["progress"], expected_progress)

    def test_questioned_completion_stays_pending(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports, task_key

        for title, completed_title in (
            ("请确认客户A是否已付款", "客户A已付款"),
            ("客户A是否已全部付款", "客户A已付款"),
            ("请确认客户A已付款了吗", "客户A已付款"),
            ("请核实客户A已付款", "客户A已付款"),
            ("客户A已付款？", "客户A已付款"),
            ("Has Customer Alpha paid invoice?", "Customer Alpha paid invoice"),
            ("Hasn't Customer Alpha paid invoice?", "Customer Alpha paid invoice"),
            ("Customer Alpha paid invoice?", "Customer Alpha paid invoice"),
            ("Is Customer Alpha payment complete?", "Customer Alpha payment complete"),
            ("Was Customer Alpha invoice paid?", "Customer Alpha invoice paid"),
            (
                "Please confirm whether Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
            (
                "Please check if Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
            (
                "Please confirm Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
            (
                "Please check Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
            (
                "Please verify Customer Alpha payment is complete.",
                "Customer Alpha payment is complete",
            ),
            (
                "Could you please confirm whether Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
            (
                "Can you confirm whether Customer Alpha payment is complete?",
                "Customer Alpha payment is complete",
            ),
        ):
            self.assertEqual(infer_status({"title": title}), "planned")
            parsed, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {title}",
                    }
                ],
                13063,
            )
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["status"], "planned")
            self.assertEqual(parsed[0]["progress"], "待确认")
            self.assertEqual(
                task_key({"title": title}),
                task_key({"title": completed_title}),
            )
            completed_chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {completed_title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(completed_chain), 1)
            self.assertEqual(completed_chain[0]["status"], "done")

        for resolved_title, expected_progress, previous_titles in (
            (
                "此前请确认客户A是否已付款，现已到账",
                "已到账",
                ("客户A未付款", "客户A尚未到账"),
            ),
            (
                "Has Customer Alpha paid invoice? Invoice paid.",
                "已付款",
                ("Customer Alpha invoice unpaid",),
            ),
            (
                "Has Customer Alpha paid invoice? Paid: Customer Alpha invoice",
                "已付款",
                ("Customer Alpha invoice unpaid",),
            ),
            (
                "Is Customer Alpha payment complete? Done: Customer Alpha payment",
                "已完成",
                ("Customer Alpha payment not complete",),
            ),
            (
                "Has Customer Alpha not paid invoice? Invoice paid.",
                "已付款",
                ("Customer Alpha invoice unpaid",),
            ),
            (
                "Is Customer Alpha payment not complete? Done: Customer Alpha payment",
                "已完成",
                ("Customer Alpha payment not complete",),
            ),
            (
                "Was Customer Alpha invoice not paid? Invoice paid.",
                "已付款",
                ("Customer Alpha invoice unpaid",),
            ),
        ):
            self.assertEqual(infer_status({"title": resolved_title}), "done")
            resolved, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {resolved_title}",
                    }
                ],
                13063,
            )
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0]["status"], "done")
            self.assertEqual(resolved[0]["progress"], expected_progress)
            for previous_title in previous_titles:
                previous = {"title": previous_title}
                changes = diff_tasks(resolved, [previous])
                self.assertEqual(changes["completed"], resolved)
                self.assertEqual(changes["progressed"], [])

        for answered_title, expected_status, expected_progress in (
            (
                "Has Customer Alpha paid invoice? Yes.",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? Yes, thanks.",
                "done",
                "已付款",
            ),
            (
                "客户A是否已付款？是的。",
                "done",
                "已付款",
            ),
            (
                "客户A是否已付款？是的，谢谢。",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? Confirmed, thanks.",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha payment been received? Confirmed: payment received.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha payment been received? Confirmed received.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha payment been received? Confirmed: funds received.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha payment been received? "
                "Confirmed: Customer Alpha payment received.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha payment been received? "
                "Confirmed: payment received yesterday.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha payment been received? "
                "Confirmed: payment received USD 10,000.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha paid invoice? Invoice paid, thanks.",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? Paid, thanks.",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha payment been received? "
                "Confirmed: payment received, thanks.",
                "done",
                "已到账",
            ),
            (
                "Has Customer Alpha paid invoice? No.",
                "stalled",
                "未完成",
            ),
            (
                "Has Customer Alpha paid invoice? Confirmed: no payment received.",
                "stalled",
                "未完成",
            ),
            (
                "Is Customer Alpha invoice partially paid? Yes.",
                "progress",
                "部分完成",
            ),
            (
                "客户A是否已部分付款？是的。",
                "progress",
                "部分完成",
            ),
            (
                "Is Customer Alpha invoice unpaid? No.",
                "done",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? Confirmed pending.",
                "planned",
                "待确认",
            ),
            (
                "Is Customer Alpha invoice not 50% paid? No.",
                "progress",
                "部分完成",
            ),
            (
                "Is Customer Alpha invoice not partially paid? No.",
                "progress",
                "部分完成",
            ),
            (
                "Has Customer Alpha paid invoice? Customer Alpha invoice unpaid.",
                "stalled",
                "未完成",
            ),
            (
                "Has Customer Alpha paid invoice? Customer Alpha invoice paid 50%.",
                "progress",
                "部分完成",
            ),
        ):
            self.assertEqual(infer_status({"title": answered_title}), expected_status)
            answered, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {answered_title}",
                    }
                ],
                13063,
            )
            self.assertEqual(len(answered), 1)
            self.assertEqual(answered[0]["status"], expected_status)
            self.assertEqual(answered[0]["progress"], expected_progress)

        for answered_title, previous_title in (
            (
                "Has Customer Alpha paid invoice? Yes.",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "客户A是否已付款？是的。",
                "客户A未付款。",
            ),
            (
                "Customer Alpha invoice paid; anything else?",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Customer Alpha invoice paid, anything else?",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Customer Alpha invoice paid. Anything else?",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Customer Alpha invoice paid: anything else?",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Is Customer Alpha invoice unpaid? No.",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Has Customer Alpha paid invoice? Yes, thanks.",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "客户A是否已付款？是的，谢谢。",
                "客户A未付款。",
            ),
            (
                "Has Customer Alpha paid invoice? Confirmed, thanks.",
                "Customer Alpha invoice unpaid.",
            ),
            (
                "Has Customer Alpha payment been received? Confirmed: payment received.",
                "Customer Alpha payment unreceived.",
            ),
            (
                "Has Customer Alpha payment been received? Confirmed: funds received.",
                "Customer Alpha payment unreceived.",
            ),
            (
                "Has Customer Alpha payment been received? "
                "Confirmed: Customer Alpha payment received.",
                "Customer Alpha payment unreceived.",
            ),
            (
                "Has Customer Alpha paid invoice? Invoice paid, thanks.",
                "Customer Alpha invoice unpaid.",
            ),
        ):
            answered = {"title": answered_title}
            previous = {"title": previous_title}
            self.assertEqual(infer_status(answered), "done")
            self.assertEqual(task_key(answered), task_key(previous))
            self.assertEqual(diff_tasks([answered], [previous])["completed"], [answered])
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous_title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {answered_title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 1)
            self.assertEqual(chain[0]["status"], "done")

        for request in (
            "Please confirm: Customer Alpha payment is complete",
            "Please check: Customer Alpha payment is complete",
            "Please verify: Customer Alpha payment is complete",
            "Please confirm, Customer Alpha payment is complete",
            "Please check, Customer Alpha payment is complete",
            "Please verify, Customer Alpha payment is complete",
            "Please confirm; Customer Alpha payment is complete",
            "Please check; Customer Alpha payment is complete",
            "Please verify; Customer Alpha payment is complete",
            "Please confirm - Customer Alpha payment is complete",
            "Please check — Customer Alpha payment is complete",
        ):
            self.assertEqual(infer_status({"title": request}), "planned")
            self.assertEqual(
                task_key({"title": request}),
                task_key({"title": "Customer Alpha payment is complete"}),
            )
            changes = diff_tasks(
                [{"title": request}],
                [{"title": "Customer Alpha payment not complete"}],
            )
            self.assertEqual(changes["completed"], [])

        confirmed_negative = {
            "title": "Has Customer Alpha paid invoice? Confirmed: no payment received."
        }
        previous_unpaid = {"title": "Customer Alpha invoice unpaid."}
        self.assertEqual(task_key(confirmed_negative), task_key(previous_unpaid))
        confirmed_chain, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T08:00:00Z",
                    "body": "1. Customer Alpha invoice unpaid.",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "1. Has Customer Alpha paid invoice? "
                    "Confirmed: no payment received.",
                },
            ],
            13063,
        )
        self.assertEqual(len(confirmed_chain), 1)
        self.assertEqual(confirmed_chain[0]["status"], "stalled")

        pending_confirmation, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T08:00:00Z",
                    "body": "1. Customer Alpha invoice unpaid.",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "1. Has Customer Alpha paid invoice? Confirmed pending.",
                },
            ],
            13063,
        )
        self.assertEqual(len(pending_confirmation), 1)
        self.assertEqual(pending_confirmation[0]["status"], "planned")

        partial_answer = {"title": "客户A是否已部分付款？是的。"}
        partial_previous = {"title": "客户A未付款。"}
        self.assertEqual(task_key(partial_answer), task_key(partial_previous))
        self.assertEqual(
            diff_tasks([partial_answer], [partial_previous])["progressed"],
            [partial_answer],
        )

        invoice_answer = {"title": "Has Customer Alpha paid? Invoice paid."}
        order_answer = {"title": "Has Customer Alpha paid? Order paid."}
        self.assertEqual(
            task_key(invoice_answer),
            task_key({"title": "Customer Alpha invoice unpaid."}),
        )
        self.assertNotEqual(task_key(invoice_answer), task_key(order_answer))

        amount_receipt = {
            "title": "Has Customer Alpha payment been received? "
            "Confirmed: payment received USD 10,000."
        }
        previous_receipt = {"title": "Customer Alpha payment unreceived."}
        self.assertEqual(
            diff_tasks([amount_receipt], [previous_receipt])["completed"],
            [amount_receipt],
        )

        self.assertEqual(
            infer_status(
                {
                    "title": "Has Customer Alpha payment been received? "
                    "Confirmed: payment received tomorrow."
                }
            ),
            "planned",
        )

    def test_short_numbered_completion_updates_previous_state(self):
        from app.duzhan_ledger import parse_owner_reports

        parsed, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T01:00:00Z",
                    "body": "1. 客户A尾款尚未付款，今天可付款",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "1. 客户A尾款已付款",
                },
            ],
            13063,
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "客户A尾款已付款")
        self.assertEqual(parsed[0]["status"], "done")
        self.assertEqual(parsed[0]["progress"], "已付款")

    def test_full_completion_wording_closes_existing_task(self):
        from app.duzhan_ledger import (
            diff_tasks,
            infer_status,
            parse_owner_reports,
            task_key,
        )

        for completed_title, previous_title, expected_progress in (
            (
                "Customer Alpha invoice paid 100%.",
                "Customer Alpha invoice unpaid.",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100%.",
                "Customer Alpha invoice unpaid.",
                "已付款",
            ),
            (
                "Customer Alpha payment received 100%.",
                "Customer Alpha payment unreceived.",
                "已到账",
            ),
            (
                "Is Customer Alpha payment complete? Complete.",
                "Customer Alpha payment not complete.",
                "已完成",
            ),
            (
                "Has Customer Alpha paid invoice? Paid in full.",
                "Customer Alpha invoice unpaid.",
                "已付款",
            ),
            (
                "Customer Alpha invoice paid in full.",
                "Customer Alpha invoice unpaid.",
                "已付款",
            ),
            (
                "Has Customer Alpha paid invoice? All paid.",
                "Customer Alpha invoice unpaid.",
                "已付款",
            ),
            ("客户A付款了", "客户A未付款", "已付款"),
            ("客户A支付了", "客户A未支付", "已付款"),
            ("客户A到账了", "客户A未到账", "已到账"),
            ("客户A完成了", "客户A未完成", "已完成"),
            ("客户A是否已付款？全部已付款。", "客户A未付款", "已付款"),
            ("客户A都已付款。", "客户A未付款", "已付款"),
        ):
            completed = {"title": completed_title}
            previous = {"title": previous_title}
            self.assertEqual(infer_status(completed), "done", completed_title)
            self.assertEqual(task_key(completed), task_key(previous), completed_title)
            self.assertEqual(
                diff_tasks([completed], [previous])["completed"],
                [completed],
                completed_title,
            )
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous_title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {completed_title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 1, completed_title)
            self.assertEqual(chain[0]["status"], "done", completed_title)
            self.assertEqual(chain[0]["progress"], expected_progress, completed_title)

        self.assertEqual(
            infer_status({"title": "Customer Alpha prepaid campaign reached 100%."}),
            "planned",
        )

    def test_plain_status_reply_updates_numbered_item(self):
        from app.duzhan_ledger import parse_owner_reports

        chain, _, evidence = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T08:00:00Z",
                    "body": "1. 客户A未付款",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "客户A今天已付款，水单已回传",
                },
            ],
            13063,
        )

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["status"], "done")
        self.assertEqual(chain[0]["progress"], "已付款")
        self.assertIn("群内提及水单", evidence)

    def test_short_plain_status_reply_updates_numbered_item(self):
        from app.duzhan_ledger import parse_owner_reports

        chain, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T08:00:00Z",
                    "body": "1. 客户A未付款",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "客户A已付款",
                },
            ],
            13063,
        )

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["status"], "done")
        self.assertEqual(chain[0]["progress"], "已付款")

    def test_plain_english_completion_updates_numbered_item(self):
        from app.duzhan_ledger import parse_owner_reports

        chain, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T08:00:00Z",
                    "body": "1. Customer Alpha invoice unpaid",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 13063,
                    "created_at": "2026-10-14T09:00:00Z",
                    "body": "Customer Alpha invoice paid",
                },
            ],
            13063,
        )

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["status"], "done")
        self.assertEqual(chain[0]["progress"], "已付款")

    def test_required_confirmation_variants_stay_open_and_merge(self):
        from app.duzhan_ledger import infer_status, parse_owner_reports, task_key

        previous_title = "Customer Alpha payment unreceived."
        cases = (
            (
                "Customer Alpha payment received today but requires bank confirmation.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today; bank confirmation is required.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today; bank confirmation is still required.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today; bank confirmation remains required.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today; bank confirmation remains pending.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today; bank confirmation is still needed.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today but is waiting for bank confirmation.",
                "stalled",
            ),
            (
                "Customer Alpha payment received today and no longer requires bank confirmation.",
                "done",
            ),
            (
                "Customer Alpha payment received today; bank confirmation is no longer required.",
                "done",
            ),
            (
                "Customer Alpha payment received today; no bank confirmation remains pending.",
                "done",
            ),
            (
                "Customer Alpha payment received today; no bank confirmation remains required.",
                "done",
            ),
            (
                "Customer Alpha payment received today; bank confirmation was pending yesterday.",
                "done",
            ),
            (
                "Customer Alpha payment received today; bank confirmation was required yesterday.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was pending; payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was required; payment received today.",
                "done",
            ),
            (
                "Customer Alpha payment received today; bank confirmation was not pending.",
                "done",
            ),
            (
                "Customer Alpha payment received today; bank confirmation was no longer required.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was pending but is still pending; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was required and is still required; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending and remains pending; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending but is no longer pending; "
                "payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was required but is no longer required; "
                "payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was needed but is no longer needed; "
                "payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was required. It is no longer required. "
                "Payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was needed. It is no longer needed. "
                "Payment received today.",
                "done",
            ),
            (
                "Customer Alpha bank confirmation was pending. It remains pending. "
                "Payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending yesterday but remains pending; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending yesterday, remains pending; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending; remains pending; "
                "payment received today.",
                "stalled",
            ),
            (
                "Customer Alpha bank confirmation was pending\nremains pending; "
                "payment received today.",
                "stalled",
            ),
        )
        for current_title, expected_status in cases:
            with self.subTest(current_title=current_title):
                self.assertEqual(infer_status({"title": current_title}), expected_status)
                self.assertEqual(task_key({"title": current_title}), task_key({"title": previous_title}))
                chain, _, _ = parse_owner_reports(
                    [
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T08:00:00Z",
                            "body": f"1. {previous_title}",
                        },
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T09:00:00Z",
                            "body": f"1. {current_title}",
                        },
                    ],
                    13063,
                )
                self.assertEqual(len(chain), 1)
                self.assertEqual(chain[0]["status"], expected_status)

    def test_negated_confirmation_continuation_merges_plain_update(self):
        from app.duzhan_ledger import parse_owner_reports

        for current_title in (
            "Customer Alpha bank confirmation was required but is no longer required; "
            "payment received today.",
            "Customer Alpha bank confirmation was needed but is no longer needed; "
            "payment received today.",
            "Customer Alpha bank confirmation was required. It is no longer required. "
            "Payment received today.",
            "Customer Alpha bank confirmation was needed. It is no longer needed. "
            "Payment received today.",
        ):
            with self.subTest(current_title=current_title):
                chain, _, _ = parse_owner_reports(
                    [
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T08:00:00Z",
                            "body": "1. Customer Alpha payment unreceived.",
                        },
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T09:00:00Z",
                            "body": current_title,
                        },
                    ],
                    13063,
                )
                self.assertEqual(len(chain), 1)
                self.assertEqual(chain[0]["status"], "done")
                self.assertEqual(chain[0]["progress"], "已到账")

    def test_elliptical_confirmation_continuation_merges_plain_update(self):
        from app.duzhan_ledger import parse_owner_reports

        for current_title in (
            "Customer Alpha bank confirmation was pending yesterday, remains pending; "
            "payment received today.",
            "Customer Alpha bank confirmation was pending; remains pending; "
            "payment received today.",
            "Customer Alpha bank confirmation was pending\nremains pending; "
            "payment received today.",
        ):
            with self.subTest(current_title=current_title):
                chain, _, _ = parse_owner_reports(
                    [
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T08:00:00Z",
                            "body": "1. Customer Alpha payment unreceived.",
                        },
                        {
                            "message_type": "text",
                            "sender_user_id": 13063,
                            "created_at": "2026-10-14T09:00:00Z",
                            "body": current_title,
                        },
                    ],
                    13063,
                )
                self.assertEqual(len(chain), 1)
                self.assertEqual(chain[0]["status"], "stalled")
                self.assertEqual(chain[0]["progress"], "未确认")

    def test_business_requirement_after_completion_does_not_mean_unconfirmed(self):
        from app.duzhan_ledger import infer_status, parse_owner_reports

        cases = (
            (
                "Customer Alpha invoice for audit unpaid.",
                "Customer Alpha invoice paid today. It is required for audit.",
                "已付款",
            ),
            (
                "Customer Alpha invoice for audit unpaid.",
                "Customer Alpha invoice paid today. It is still required for audit.",
                "已付款",
            ),
            (
                "Customer Alpha invoice for audit unpaid.",
                "Customer Alpha invoice paid today. It remains required for audit.",
                "已付款",
            ),
            (
                "Customer Alpha payment for order release unreceived.",
                "Customer Alpha payment received today. It is needed for order release.",
                "已到账",
            ),
            (
                "Customer Alpha payment for order release unreceived.",
                "Customer Alpha payment received today. It is still needed for order release.",
                "已到账",
            ),
            (
                "Customer Alpha payment for order release unreceived.",
                "Customer Alpha payment received today. It remains needed for order release.",
                "已到账",
            ),
        )
        for previous_title, current_title, expected_progress in cases:
            self.assertEqual(infer_status({"title": current_title}), "done")
            for prefix in ("", "1. "):
                with self.subTest(current_title=current_title, prefix=prefix):
                    chain, _, _ = parse_owner_reports(
                        [
                            {
                                "message_type": "text",
                                "sender_user_id": 13063,
                                "created_at": "2026-10-14T08:00:00Z",
                                "body": f"1. {previous_title}",
                            },
                            {
                                "message_type": "text",
                                "sender_user_id": 13063,
                                "created_at": "2026-10-14T09:00:00Z",
                                "body": f"{prefix}{current_title}",
                            },
                        ],
                        13063,
                    )
                    self.assertEqual(len(chain), 1)
                    self.assertEqual(chain[0]["status"], "done")
                    self.assertEqual(chain[0]["progress"], expected_progress)

    def test_unconfirmed_receipt_language_stays_open(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports

        previous = {"title": "Customer Alpha payment unreceived."}
        for title in (
            "Has Customer Alpha payment been received? "
            "Pending confirmation: payment received.",
            "Has Customer Alpha payment been received? "
            "Unable to confirm payment received.",
            "Has Customer Alpha payment been received? "
            "Awaiting confirmation: payment received.",
        ):
            current = {"title": title}
            self.assertEqual(infer_status(current), "stalled", title)
            self.assertEqual(diff_tasks([current], [previous])["completed"], [], title)
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous['title']}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 1, title)
            self.assertEqual(chain[0]["status"], "stalled", title)

    def test_completion_qualifiers_keep_items_open(self):
        from app.duzhan_ledger import diff_tasks, infer_status, parse_owner_reports, task_key

        for title in (
            "客户A需求已确认且款项今天已到账",
            "客户A需求已核实合同已完成",
        ):
            self.assertEqual(infer_status({"title": title}), "done", title)

        for title in (
            "Review all paid media campaigns.",
            "Audit fully paid media campaign.",
            "Audit fully paid-media campaign.",
            "Paid-media campaign launched.",
            "Customer Alpha 100% paid media budget planned.",
            "Customer Alpha 100% paid-media budget planned.",
            "Customer Alpha 50% paid media budget planned.",
            "Audit partially paid media campaign.",
        ):
            self.assertEqual(infer_status({"title": title}), "planned", title)

        for title, previous_title, expected_status, expected_progress in (
            ("客户A不付款了", "客户A未付款", "stalled", "未完成"),
            ("客户A拒绝付款了", "客户A未付款", "stalled", "未完成"),
            ("客户A停止付款了", "客户A未付款", "stalled", "未完成"),
            (
                "Customer Alpha invoice is almost 100% paid.",
                "Customer Alpha invoice unpaid.",
                "progress",
                "部分完成",
            ),
            (
                "Customer Alpha invoice is less than 100% paid.",
                "Customer Alpha invoice unpaid.",
                "progress",
                "部分完成",
            ),
            ("客户A接近100%已付款", "客户A未付款", "progress", "部分完成"),
            ("客户A已付款接近100%", "客户A未付款", "progress", "部分完成"),
            (
                "Has Customer Alpha paid invoice? Paid 100% tomorrow.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid in full tomorrow.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% by tomorrow.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% next Monday.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% by next Monday.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid in full on next Monday.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% by next Friday.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid in full this Friday.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% by the end of day.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            (
                "Has Customer Alpha paid invoice? Paid 100% by EOD.",
                "Customer Alpha invoice unpaid.",
                "planned",
                "待确认",
            ),
            ("客户A已到账，待确认", "客户A未到账", "stalled", "未确认"),
            ("客户A已到账但未确认", "客户A未到账", "stalled", "未确认"),
            ("客户A已到账但尚未核实", "客户A未到账", "stalled", "未确认"),
            ("客户A已到账但还没确认", "客户A未到账", "stalled", "未确认"),
            ("客户A已到账但待财务确认", "客户A未到账", "stalled", "未确认"),
            ("客户A今天已到账但需要确认", "客户A未到账", "stalled", "未确认"),
            ("客户A今天已到账但仍需财务确认", "客户A未到账", "stalled", "未确认"),
            ("客户A今天已到账，需要确认", "客户A未到账", "stalled", "未确认"),
            ("客户A今天已到账，仍需财务确认", "客户A未到账", "stalled", "未确认"),
            ("客户A已付款，需要财务确认", "客户A未付款", "stalled", "未确认"),
            ("客户A已付款，仍需财务确认", "客户A未付款", "stalled", "未确认"),
            ("客户A待财务确认后已到账", "客户A未到账", "done", "已到账"),
            ("客户A待确认，现已到账", "客户A未到账", "done", "已到账"),
            ("客户A仍待确认，但今天已到账", "客户A未到账", "stalled", "未确认"),
            ("客户A仍需财务确认，虽然今天已到账", "客户A未到账", "stalled", "未确认"),
            ("客户A尚未确认，但今天已到账", "客户A未到账", "stalled", "未确认"),
            (
                "Customer Alpha payment has been received but unconfirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment awaiting confirmation yesterday; "
                "payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received today; "
                "yesterday it was awaiting confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was unconfirmed, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was pending confirmation, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was awaiting confirmation, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was still unconfirmed, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was still pending confirmation, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment had remained unconfirmed, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was received today but was not confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment was not confirmed, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was not yet confirmed, but payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment was received today but was pending confirmation.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment was received today but was unconfirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            ("客户A已付款，无需待确认", "客户A未付款", "done", "已付款"),
            ("客户A已到账，不需等待确认", "客户A未到账", "done", "已到账"),
            ("客户A已到账，不再等待确认", "客户A未到账", "done", "已到账"),
            ("客户A已到账，已无需财务确认", "客户A未到账", "done", "已到账"),
            ("客户A已到账，不再需要确认", "客户A未到账", "done", "已到账"),
            (
                "Customer Alpha payment received; not awaiting confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received; no longer pending confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received; no longer unconfirmed.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received; not unverified.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment has been received but awaiting finance confirmation.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment has been received but pending finance confirmation.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but awaiting bank verification.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but still needs bank confirmation.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha invoice paid today but still needs bank confirmation.",
                "Customer Alpha invoice unpaid.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha invoice paid today but needs bank confirmation.",
                "Customer Alpha invoice unpaid.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment pending confirmation; payment received today.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment still pending confirmation, but payment received today.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment is unconfirmed, although payment received today.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment remains unconfirmed, although payment received today.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but has not been confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but hasn't been confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but isn't confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but couldn't be confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today and does not need bank confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received today and needs no further confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received today and no longer needs bank confirmation.",
                "Customer Alpha payment unreceived.",
                "done",
                "已到账",
            ),
            (
                "Customer Alpha payment received today but could not be confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment has been received but cannot be confirmed.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            (
                "Customer Alpha payment received today but was unable to be verified.",
                "Customer Alpha payment unreceived.",
                "stalled",
                "未确认",
            ),
            ("张三都已付款", "张三未付款", "done", "已付款"),
        ):
            current = {"title": title}
            previous = {"title": previous_title}
            self.assertEqual(infer_status(current), expected_status, title)
            if title != "张三都已付款":
                self.assertEqual(task_key(current), task_key(previous), title)
            changes = diff_tasks([current], [previous])
            self.assertEqual(
                changes["completed"],
                [current] if expected_status == "done" else [],
                title,
            )
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous_title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 1, title)
            self.assertEqual(chain[0]["status"], expected_status, title)
            self.assertEqual(chain[0]["progress"], expected_progress, title)

        for title, previous_title in (
            ("客户订单都已付款", "客户订单未付款"),
            ("三个订单都已付款", "三个订单未付款"),
            ("欧阳娜娜都已付款", "欧阳娜娜未付款"),
            ("经销商都已付款", "经销商未付款"),
            ("门店都已完成", "门店未完成"),
            ("张三李四都已付款", "张三李四未付款"),
            ("所有人都已完成", "所有人未完成"),
            ("双方都已付款", "双方未付款"),
            ("负责人都已完成", "负责人未完成"),
            ("所有同事都已完成", "所有同事未完成"),
        ):
            current = {"title": title}
            previous = {"title": previous_title}
            self.assertEqual(infer_status(current), "done", title)
            self.assertEqual(diff_tasks([current], [previous])["completed"], [current], title)
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous_title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 1, title)
            self.assertEqual(chain[0]["status"], "done", title)

        self.assertEqual(
            task_key({"title": "成都已付款"}),
            task_key({"title": "成都未付款"}),
        )
        for current_title, previous_title in (
            ("成都已付款", "成未付款"),
            ("新华都已付款", "新华未付款"),
            ("大成都已付款", "大成未付款"),
        ):
            current = {"title": current_title}
            previous = {"title": previous_title}
            changes = diff_tasks([current], [previous])
            self.assertEqual(changes["completed"], [], current_title)
            self.assertEqual(changes["new"], [current], current_title)
            self.assertEqual(changes["unanswered"], [previous], current_title)
            chain, _, _ = parse_owner_reports(
                [
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T08:00:00Z",
                        "body": f"1. {previous_title}",
                    },
                    {
                        "message_type": "text",
                        "sender_user_id": 13063,
                        "created_at": "2026-10-14T09:00:00Z",
                        "body": f"1. {current_title}",
                    },
                ],
                13063,
            )
            self.assertEqual(len(chain), 2, current_title)

    def test_parse_water_slip_and_loose_plan(self):
        from app.duzhan_ledger import parse_owner_reports

        collections, _, evidence = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 13122,
                    "created_at": "2026-09-15T14:31:13Z",
                    "body": "俄罗斯索契：10台Alpha、10台Meta 2，水单已回传43万RMB。",
                },
                {
                    "message_type": "text",
                    "sender_user_id": 14113,
                    "created_at": "2026-09-15T14:55:53Z",
                    "body": (
                        "明日工作安排\n"
                        "继续寻找印度人托运的运输方式，协助Velocity成单；\n"
                        "CEO of ULTAVO 二轮会议讨论合作事宜"
                    ),
                },
            ],
            13122,
        )
        sochi = next(item for item in collections if "索契" in item["title"])
        self.assertEqual(sochi["status"], "done")
        self.assertIn("水单", "".join(evidence) + sochi["title"])
        haiwen, _, _ = parse_owner_reports(
            [
                {
                    "message_type": "text",
                    "sender_user_id": 14113,
                    "created_at": "2026-09-15T14:55:53Z",
                    "body": (
                        "明日工作安排\n"
                        "继续寻找印度人托运的运输方式，协助Velocity成单；\n"
                        "CEO of ULTAVO 二轮会议讨论合作事宜"
                    ),
                }
            ],
            14113,
        )
        self.assertTrue(any("Velocity" in item["title"] for item in haiwen))
        self.assertTrue(any("ULTAVO" in item["title"] for item in haiwen))

    def test_run_duzhan_passes_idempotency_key(self):
        empty = {"day": "2026-09-15", "people": [], "red": [], "black": []}
        with patch("app.duzhan.push_duzhan_message", return_value=True) as push, patch(
            "app.duzhan.collect_ledger", return_value=empty
        ):
            run_duzhan(
                TZ_PARIS,
                10,
                datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo(TZ_PARIS)),
            )
        key = push.call_args.kwargs["idempotency_key"]
        self.assertTrue(key.startswith("duzhan-20260915-1000-"))
        self.assertIn("e435ab5d", key)


class DuzhanCompactSlotTests(unittest.TestCase):
    """2026-09-19 起三档只出总结性内容（明细走每天 08:00 的证据 HTML）。"""

    def setUp(self):
        from app.config import get_settings

        settings = get_settings()
        self._compact_backup = settings.duzhan_compact
        settings.duzhan_compact = True
        self.addCleanup(self._restore_compact)

    def _restore_compact(self):
        from app.config import get_settings

        get_settings().duzhan_compact = self._compact_backup

    def _person(self, **over: object) -> dict:
        row = {
            "group": "于冰业绩达标群",
            "display": "于冰",
            "target_wan": 200,
            "mtd_wan": 170.2,
            "daily_target_wan": 6.67,
            "rolling_target_wan": 123.4,
            "target_gap_wan": 46.8,
            "target_ahead": True,
            "perf_arrived_wan": 170.2,
            "perf_slip": [{"amount_text": "USD 45,022", "wan": 32.0, "snippet": "水单已回传"}],
            "perf_intent": [{"amount_text": "120万", "wan": 120.0, "snippet": "明确意向"}],
            "wa_reached": 15,
            "wa_lower_bound": False,
            "intent_count": 2,
            "hours_minutes": 396.0,
            "hours_band": "近满勤",
            "mto_count": 4,
            "mto_names": ["2.webp"],
            "collections": [
                {"title": "迪拜 Billionaire 订单确认", "status": "progress"},
                {"title": "马来 Derict D 回复", "status": "stalled"},
            ],
            "blockers": [],
            "evidence": ["$38246"],
        }
        row.update(over)
        return row

    def _ledger(self, person: dict) -> dict:
        return {"day": "2026-09-19", "today_target": "1300万战役", "people": [person], "red": [], "black": []}

    def test_compact_is_default_and_short(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text = render_brief(group, 10, now, self._ledger(self._person()))
        self.assertIn("经销商一部", text)
        self.assertIn("部门月目标：待确认", text)
        self.assertIn("请回：本部今日3–5项交付物和截止时间。", text)
        # 明细不该出现在档位里
        self.assertNotIn("业绩三关键词", text)
        self.assertNotIn("VPS 留痕", text)
        self.assertNotIn("Vemory", text)
        self.assertLessEqual(len(text.splitlines()), 12)

    def test_compact_midday_evening_lines(self):
        group = _group("于冰业绩达标群")
        now15 = datetime(2026, 9, 19, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = self._person(perf_arrived_wan=150.2)
        text15 = render_brief(group, 15, now15, self._ledger(self._person()), self._ledger(prev))
        self.assertIn("本档新增：+20万", text15)
        self.assertIn("请回：相对 10:00 的变化", text15)
        now20 = datetime(2026, 9, 19, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text20 = render_brief(group, 20, now20, self._ledger(self._person()), self._ledger(prev))
        self.assertIn("累计已录单170.2万", text20)
        self.assertIn("水单：于冰：USD 45,022", text20)
        self.assertIn("意向金额：于冰：120万", text20)
        self.assertIn("WhatsApp触达15户次（明确意向2户次）", text20)
        self.assertIn("明日第一动作：于冰：迪拜 Billionaire 订单确认", text20)
        self.assertNotIn("附件证据", text20)

    def test_compact_keeps_amount_ping(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 19, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(perf_intent=[{"amount_text": "", "wan": None, "snippet": "意向金额待定"}])
        text = render_brief(group, 15, now, self._ledger(person), self._ledger(self._person()))
        self.assertIn("待补金额1条", text)
        self.assertNotIn("补一句：", text)

    def test_long_format_still_available(self):
        from app.config import get_settings

        settings = get_settings()
        backup = getattr(settings, "duzhan_compact", True)
        settings.duzhan_compact = False
        try:
            group = _group("于冰业绩达标群")
            now = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
            text = render_brief(group, 10, now, self._ledger(self._person()))
            self.assertIn("业绩三关键词", text)
        finally:
            settings.duzhan_compact = backup


class DuzhanSlotStructureTests(LongFormatMixin, unittest.TestCase):
    """A 档位结构增量：10:00 定目标 / 15:00 上午总结 / 20:00 兑现核对。"""

    def _person(self, **over: object) -> dict:
        row = {
            "group": "于冰业绩达标群",
            "display": "于冰",
            "target_wan": 200,
            "mtd_wan": 170.2,
            "daily_target_wan": 6.67,
            "rolling_target_wan": 120.1,
            "days_elapsed": 18,
            "days_in_month": 30,
            "target_gap_wan": 50.1,
            "target_ahead": True,
            "perf_arrived_wan": 170.2,
            "perf_slip": [{"amount_text": "USD 45,022", "wan": 32.0, "snippet": "水单已回传"}],
            "perf_intent": [{"amount_text": "120万", "wan": 120.0, "snippet": "明确意向"}],
            "wa_reached": 15,
            "wa_lower_bound": False,
            "intent_count": 2,
            "hours_minutes": 396.0,
            "hours_band": "近满勤",
            "mto_count": 4,
            "mto_names": ["2.webp"],
            "collections": [
                {"title": "越南尾款 38246$ XSD", "status": "done"},
                {"title": "迪拜 Billionaire 订单确认", "status": "progress"},
                {"title": "马来 Derict D 回复", "status": "stalled"},
            ],
            "blockers": [],
            "evidence": ["$38246"],
        }
        row.update(over)
        return row

    def _ledger(self, person: dict, day: str = "2026-09-18") -> dict:
        return {
            "day": day,
            "today_target": "1300万战役",
            "people": [person],
            "red": [],
            "black": [],
        }

    def test_morning_slot_locks_target_and_carries_yesterday(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = self._person(
            perf_arrived_wan=140.0,
            collections=[
                {"title": "越南尾款 38246$ XSD", "status": "progress"},
                {"title": "迪拜 Billionaire 订单确认", "status": "planned"},
            ],
        )
        text = render_brief(group, 10, now, self._ledger(self._person()), self._ledger(prev))
        self.assertIn("0. 今日目标（本档先定）", text)
        self.assertIn("日目标 6.67 万/天，累计应达 120.1 万", text)
        self.assertIn("领先 50.1 万", text)
        self.assertIn("昨日未闭环结转（今日第一动作）", text)
        self.assertIn("越南尾款 38246$ XSD", text)

    def test_morning_slot_without_target_says_pending(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(
            target_wan=None,
            daily_target_wan=None,
            rolling_target_wan=None,
            target_gap_wan=None,
        )
        text = render_brief(group, 10, now, self._ledger(person))
        self.assertIn("0. 今日目标（本档先定）：待确认（缺月度目标）", text)

    def test_morning_slot_uses_group_level_target_for_newcomers(self):
        """小组口径目标：个人没有月目标时按整组目标考核、不摊人头。

        2026-10-10 新人小组群停推，同款口径改由 Q4五百万 群承载。
        """
        group = _group("Q4五百万")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(
            group="Q4五百万",
            display="邓琳莹",
            target_wan=None,
            daily_target_wan=None,
            rolling_target_wan=None,
            target_gap_wan=None,
            group_target_wan=500.0,
            group_target_name="Q4五百万",
        )
        text = render_brief(group, 10, now, self._ledger(person))
        self.assertIn("0. 今日目标（本档先定）：小组口径 Q4五百万 500 万/月", text)
        self.assertIn("（Q4五百万整体考核，不摊人头）", text)
        self.assertNotIn("缺月度目标", text)

    def test_morning_pings_missing_amounts_from_prev_slot(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = self._person(
            perf_slip=[{"amount_text": "", "wan": None, "snippet": "水单已回传，金额在邮件里"}],
            perf_intent=[],
        )
        person = self._person(perf_slip=[], perf_intent=[])
        text = render_brief(group, 10, now, self._ledger(person), self._ledger(prev))
        self.assertIn("补一句：水单/意向有 1 条没写金额", text)
        self.assertIn("按「客户 / 金额+币种 / 预计到账日 / 品类」补一句", text)

    def test_midday_pings_missing_amounts_from_current_slot(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(
            perf_intent=[{"amount_text": "", "wan": None, "snippet": "客户有明确意向，金额待定"}],
        )
        text = render_brief(group, 15, now, self._ledger(person), self._ledger(self._person()))
        self.assertIn("补一句：水单/意向有 1 条没写金额", text)

    def test_no_ping_when_amounts_are_clear(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text = render_brief(group, 15, now, self._ledger(self._person()), self._ledger(self._person()))
        self.assertNotIn("补一句", text)

    def test_evening_slot_has_no_amount_ping(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(perf_intent=[{"amount_text": "", "wan": None, "snippet": "意向待定"}])
        text = render_brief(group, 20, now, self._ledger(person), self._ledger(person))
        self.assertNotIn("补一句", text)

    def test_midday_slot_reports_delta_not_month_over_day(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = self._person(perf_arrived_wan=150.2)
        text = render_brief(group, 15, now, self._ledger(self._person()), self._ledger(prev))
        self.assertIn("【目标梳理｜上午总结】", text)
        self.assertIn("本次新增 +20.0 万", text)
        self.assertIn("累计已录单 170.2 万｜累计应达 120.1 万（领先 50.1 万）｜今日日目标 6.67 万", text)
        self.assertIn("上午工作：6.6h / 标准8h（近满勤）", text)
        # 月累计 ÷ 日目标 的荒唐完成率不允许再出现
        self.assertNotIn("完成率", text)

    def test_midday_slot_without_prev_says_pending(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 15, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text = render_brief(group, 15, now, self._ledger(self._person()), None)
        self.assertIn("本次新增 待确认（缺上一档口径）", text)

    def test_evening_slot_covers_perf_whatsapp_hours_and_tomorrow(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        prev = self._person(
            collections=[
                {"title": "越南尾款 38246$ XSD", "status": "progress"},
                {"title": "迪拜 Billionaire 订单确认", "status": "progress"},
            ]
        )
        text = render_brief(group, 20, now, self._ledger(self._person()), self._ledger(prev))
        self.assertIn("【当天总结｜业绩核对】", text)
        self.assertIn("已录单", text)
        self.assertIn("水单", text)
        self.assertIn("意向", text)
        self.assertIn("WhatsApp：15 户｜明确意向 2 户", text)
        self.assertIn("当日工时：", text)
        self.assertIn("【明日预告】", text)
        self.assertIn("迪拜 Billionaire 订单确认", text)

    def test_meeting_todos_block_is_appended_once(self):
        """回归：第 8 节早会待办只允许拼一次（工作区曾出现重复的一行）。"""
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(meeting_todos="\n【第 8 节｜早会待办】\n   • 事项A")
        text = render_brief(group, 10, now, self._ledger(person), self._ledger(person))
        self.assertEqual(text.count("【第 8 节｜早会待办】"), 1)

    def test_evening_slot_shows_mto_scoring(self):
        """MTO 打分放在 20:00 验兑现（2026-09-23 老板要求：10:00 那档早上没图必然 0）。"""
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(
            mto_quotes=[
                {"model": "VertuAlphafold", "wan": 63.3, "qualifies": True},
                {"model": "VertuQuantum", "wan": 20.2, "qualifies": False},
                {"model": "", "wan": None, "qualifies": False},
            ]
        )
        text = render_brief(group, 20, now, self._ledger(person), self._ledger(person))
        self.assertIn("• MTO 今日达标：1/3 款达标（VertuAlphafold 63.3万）", text)
        self.assertIn("1 款未满 30 万（VertuQuantum 20.2万）", text)
        self.assertIn("1 张读不出金额", text)

    def test_evening_slot_mto_pending_when_no_data(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(mto_count=None, mto_quotes=None)
        text = render_brief(group, 20, now, self._ledger(person), self._ledger(person))
        self.assertIn("• MTO 今日达标：待确认", text)

    def test_morning_slot_keeps_summary_without_wrapup_line(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 10, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        text = render_brief(
            group, 10, now, self._ledger(self._person()), self._ledger(self._person())
        )
        self.assertIn("• 摘要：", text)
        self.assertNotIn("• MTO 今日达标：", text)

    def test_evening_slot_gives_first_action_when_nothing_open(self):
        group = _group("于冰业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_SHANGHAI))
        person = self._person(collections=[{"title": "已办完", "status": "done"}])
        text = render_brief(group, 20, now, self._ledger(person), self._ledger(person))
        self.assertIn("无未完成事项，按日目标继续推进", text)

    def test_lina_slot_sections_are_english(self):
        group = _group("Lina业绩达标群")
        now = datetime(2026, 9, 18, 20, 0, tzinfo=ZoneInfo(TZ_PARIS))
        person = self._person(group="Lina业绩达标群", display="Lina")
        text = render_brief(group, 20, now, self._ledger(person), self._ledger(person))
        self.assertIn("【Day wrap-up | Performance check】", text)
        self.assertIn("WhatsApp:", text)
        self.assertIn("Hours today:", text)
        self.assertIn("【Tomorrow】First action:", text)
        self.assertNotIn("【当天总结｜业绩核对】", text)


if __name__ == "__main__":
    unittest.main()
