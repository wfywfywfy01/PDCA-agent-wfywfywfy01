"""Task-only members participate in sales and closure, without sales process quotas."""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.duzhan import GROUPS, render_brief, render_person_briefs, run_duzhan
from app.duzhan_departments import DEPARTMENTS


class TaskOnlyScope(TestCase):
    def setUp(self):
        self.group = next(group for group in GROUPS if group.name == "Q4五百万")
        self.now = datetime(2026, 10, 21, 10, tzinfo=ZoneInfo(self.group.tz))
        self.rows = [dict(group=self.group.name, display=name, perf_arrived_wan=amount,
                          history_ok=True, mto_count=0, mto_quotes=[], daily_report_ok=True,
                          collections=[dict(title=f"{name}客户合同", status="planned")])
                     for name, amount in (("邓琳莹", 1), ("刘春梅", 2), ("付汪阳", 3))]
        self.ledger = {"people": self.rows}
        self.settings = patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=True))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        for target in ("app.meeting_todos.items_for_group", "app.weekly_focus.items_for"):
            active = patch(target, return_value=[])
            active.start()
            self.addCleanup(active.stop)

    def test_thirteen_task_members_but_ten_sales_process_members(self):
        self.assertEqual(sum(len(item.members) for item in DEPARTMENTS), 13)
        self.assertEqual(sum(len(item.metric_members) for item in DEPARTMENTS), 10)
        self.assertEqual({name for item in DEPARTMENTS for name in item.task_only_members},
                         {"冯磊", "刘春梅", "付汪阳"})

    def test_all_slots_chase_task_only_todos_without_extra_mto_or_reports(self):
        for hour in (10, 15, 20):
            text = render_brief(self.group, hour, self.now, self.ledger)
            self.assertIn("刘春梅客户合同", text)
            self.assertIn("付汪阳客户合同", text)
            if hour == 10:
                self.assertIn("累计已录单6万", text)
                self.assertIn("MTO计划：共4款", text)
            if hour == 20:
                mto = next(line for line in text.splitlines() if line.startswith("MTO核验"))
                reports = next(line for line in text.splitlines() if line.startswith("日报核对"))
                self.assertIn("0/1", mto)
                self.assertNotIn("刘春梅", mto + reports)
                self.assertNotIn("付汪阳", mto + reports)

    def test_missing_task_only_sales_or_history_stays_pending(self):
        self.rows[-1].update(perf_arrived_wan=None, history_ok=False)
        text = render_brief(self.group, 20, self.now, self.ledger)
        self.assertIn("累计已录单待确认", text)
        self.assertIn("闭环核对：待确认：付汪阳", text)

    def test_ai_and_report_condition_respect_task_only_role(self):
        from app.duzhan_admin.ai_rules import _digest, _rule_matches
        from app.duzhan_blocks import parse_blocks

        self.rows[0]["daily_report"] = {"submitted": True}
        rule = parse_blocks({"blocks": [{"type": "rule", "when": "missing_report", "text": "补日报"}]})[0]
        self.assertFalse(_rule_matches(rule, self.group, "2026-10-21", self.ledger))
        facts = _digest(self.group, 10, "2026-10-21", self.ledger)
        self.assertIn("刘春梅客户合同", facts)
        self.assertIn("付汪阳客户合同", facts)
        self.assertIn("仅追待办", facts)

    def test_preview_labels_task_only_members_as_chased_for_todos(self):
        from app.duzhan_admin.service import preview_agent
        from app.models.duzhan_agent import DuzhanAgent

        blocks = [{"type": "group", "channel_id": self.group.channel_id},
                  {"type": "times", "slots": ["10:00"]}]
        result = preview_agent(DuzhanAgent(name="五部", blocks_json=json.dumps({"blocks": blocks})))
        self.assertEqual(result["spec"]["people"], ["邓琳莹", "刘春梅", "付汪阳"])
        self.assertEqual(result["spec"]["task_only_people"], ["刘春梅", "付汪阳"])
        self.assertTrue(any("仅追待办" in line for line in result["summary"]))

    def test_long_and_cached_long_copy_chase_todos_without_sales_specialties(self):
        snapshot = {"ledger": self.ledger, "person_messages": {self.group.channel_id: [
            {"display": "刘春梅", "text": "刘春梅补交MTO和日报"}]}}
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)), \
             patch("app.duzhan.load_prepared", return_value=snapshot), \
             patch("app.duzhan.groups_for_tz", return_value=[self.group]), \
             patch("app.duzhan._previous_prepared_for_group", return_value=None), \
             patch("app.duzhan_admin.runtime.using_db", return_value=False), \
             patch("app.duzhan.push_duzhan_message", return_value=True) as push:
            parts = render_person_briefs(self.group, 20, self.now, self.ledger)
            for part in parts:
                if part["display"] in ("刘春梅", "付汪阳"):
                    self.assertIn("客户合同", part["text"])
                    for label in ("MTO", "WhatsApp", "日报"):
                        self.assertNotIn(label, part["text"])
            run_duzhan(self.group.tz, 10, self.now)
        self.assertEqual(push.call_count, 3)
        text = "\n".join(call.args[0] for call in push.call_args_list)
        self.assertIn("刘春梅客户合同", text)
        self.assertNotIn("刘春梅补交MTO和日报", text)

    def test_feng_identity_uses_exact_sales_alias(self):
        from app.duzhan_ledger import OWNERS, _mtd_wan

        feng = next(owner for owner in OWNERS if owner.display == "冯磊")
        self.assertEqual(feng.im_user_id, 12545)
        self.assertEqual(_mtd_wan(feng, [{"salesperson": "冯磊-1", "sales_amount": 200000},
                                       {"salesperson": "冯磊-10", "sales_amount": 9990000}]), 20)
        for value in (None, "", True, "bad", float("inf")):
            self.assertIsNone(_mtd_wan(feng, [{"salesperson": "冯磊-1", "sales_amount": value}]))

    def test_collection_parses_all_three_task_owners_and_skips_specialty_sources(self):
        from app import duzhan_ledger as dl

        owners = tuple(owner for owner in dl.OWNERS if owner.display in ("冯磊", "刘春梅", "付汪阳"))
        self.assertEqual(len(owners), 3)
        messages = [
            {
                "id": f"message-{owner.im_user_id}",
                "message_type": "image",
                "sender_user_id": owner.im_user_id,
                "created_at": "2026-10-21T02:00:00Z",
                "attachments": [{
                    "id": f"image-{owner.im_user_id}",
                    "attachment_type": "image",
                    "url": f"/synthetic/{owner.im_user_id}.jpg",
                }],
            }
            for owner in owners
        ]
        with patch.object(dl, "OWNERS", owners), \
             patch.object(dl, "get_settings", return_value=SimpleNamespace(todo_group_channel_id="report")), \
             patch.object(dl, "fetch_personal_okr", return_value=[]), \
             patch.object(dl, "load_vps_activity", return_value={}), \
             patch.object(dl, "fetch_vemory_day", return_value=[]), \
             patch.object(dl, "load_month_targets", return_value={}), \
             patch.object(dl, "warn_target_fallback"), \
             patch.object(dl, "fetch_channel_history", return_value=messages), \
             patch.object(dl, "_subject", return_value={"employee_id": 1}), \
             patch.object(dl, "_mcp_bundle") as mcp, \
             patch.object(dl, "parse_performance_buckets", return_value={"slip": [], "intent": []}) as buckets, \
             patch.object(dl, "match_daily_report", return_value={"submitted": True, "item_count": 1}), \
             patch.object(dl, "parse_owner_reports", return_value=([dict(title="确认合同", status="planned")], [], [])) as parse, \
             patch("app.meeting_todos.block_for_group", return_value=""), \
             patch("app.mto_ocr.review_mto_images") as ocr:
            rows = dl.collect_ledger("2026-10-21")["people"]
        self.assertEqual({call.args[1] for call in parse.call_args_list}, {12545, 12564, 13365})
        self.assertTrue(all(row["collections"][0]["title"] == "确认合同" and row["history_ok"] for row in rows))
        ocr.assert_not_called()
        mcp.assert_not_called()
        self.assertEqual(buckets.call_count, 3)
        self.assertTrue(all("群图片1张待核（未计入系统已录单业绩）" in row["evidence"] for row in rows))
        self.assertTrue(all(not any(str(item).startswith("海外日报已交") for item in row["evidence"]) for row in rows))

    def test_ai_cache_includes_task_only_roles(self):
        from app.duzhan_admin.ai_rules import _cache_path
        from app.duzhan_blocks import parse_blocks

        rule = parse_blocks({"blocks": [{"type": "rule", "mode": "ai", "prompt": "追待办"}]})[0]
        members = ("邓琳莹", "刘春梅", "付汪阳")
        self.assertNotEqual(_cache_path(1, "2026-10-21", 10, rule, cohort=members),
                            _cache_path(1, "2026-10-21", 10, rule, cohort=members,
                                        task_only=("刘春梅", "付汪阳")))

    def test_old_long_snapshot_keeps_missing_owners_and_carries_open_todos(self):
        previous = {"people": [dict(self.rows[1], collections=[dict(title="上一档未完成合同", status="planned")])]}
        self.rows[1]["collections"] = []
        self.rows.pop()
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            parts = render_person_briefs(self.group, 10, self.now, self.ledger, previous)
        self.assertEqual({part["display"] for part in parts}, {"邓琳莹", "刘春梅", "付汪阳"})
        self.assertIn("上一档未完成合同", next(part["text"] for part in parts if part["display"] == "刘春梅"))
        self.assertIn("采集待确认", next(part["text"] for part in parts if part["display"] == "付汪阳"))

    def test_task_only_members_do_not_require_new_personal_targets(self):
        from app import duzhan_ledger as dl

        owners = tuple(owner for owner in dl.OWNERS if owner.display in ("冯磊", "刘春梅", "付汪阳"))
        with patch.object(dl, "OWNERS", owners):
            self.assertEqual(dl.month_target_scope("2026-10-21", {"于冰": 200}), (True, []))

    def test_task_only_sales_specialties_do_not_enter_department_or_ai_output(self):
        from app.duzhan_admin.ai_rules import _digest

        self.rows[1].update(perf_slip=[dict(amount_text="TASK_ONLY_SLIP", wan=10)],
                            perf_intent=[dict(amount_text="TASK_ONLY_INTENT", wan=20)])
        text = render_brief(self.group, 20, self.now, self.ledger) + _digest(self.group, 20, "2026-10-21", self.ledger)
        self.assertNotIn("TASK_ONLY_SLIP", text)
        self.assertNotIn("TASK_ONLY_INTENT", text)

    def test_evidence_and_digest_show_todos_and_sales_without_specialty_assessment(self):
        from app.evidence_report import build_html, person_card
        from app.daily_digest import build_digest

        row = self.rows[1]
        row.update(score=999, mtd_wan=2, wa_reached=123, mto_count=4, daily_report={})
        text = person_card(row, [], [])
        self.assertIn("刘春梅客户合同", text)
        self.assertIn("已录单", text)
        self.assertIn("仅追待办", text)
        for label in ("MTO", "WhatsApp", "工时", "日报", "评分"):
            self.assertNotIn(label, text)
        self.ledger["red"] = [dict(display="刘春梅", group=self.group.name, score=999, combined_score=999)]
        html = build_html("2026-10-21", self.ledger)
        self.assertNotIn("综合999", html)
        digest = build_digest("2026-10-22", self.ledger, ledger_day="2026-10-21")
        self.assertIn("MTO：4 款达标 0/1 人", digest)
        self.assertIn("刘春梅客户合同", digest)
        individual = next(line for line in digest.splitlines() if line.startswith("   • 刘春梅："))
        self.assertIn("仅追待办", individual)

    def test_old_quota_tasks_and_generated_report_evidence_do_not_return(self):
        from app.duzhan_admin.ai_rules import _digest
        from app.evidence_report import person_card

        row = self.rows[1]
        row["collections"] = [dict(title="补交4款MTO和正式日报", status="planned"),
                              dict(title="跟进徐豪MTO报价", status="planned")]
        row["evidence"] = ["海外日报已交1项/1h", "MTO图 旧报价.png", "客户A付款凭证"]
        text = render_brief(self.group, 20, self.now, self.ledger)
        text += _digest(self.group, 20, "2026-10-21", self.ledger)
        text += person_card(row, [], [])
        with patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=False)):
            text += "\n".join(part["text"] for part in render_person_briefs(self.group, 20, self.now, self.ledger))
        self.assertNotIn("补交4款MTO和正式日报", text)
        self.assertNotIn("海外日报已交", text)
        self.assertNotIn("MTO图 旧报价.png", text)
        self.assertIn("跟进徐豪MTO报价", text)
        self.assertIn("客户A付款凭证", text)

    def test_task_only_message_headers_are_recognized_as_own_bot(self):
        from app.duzhan import is_own_bot_message

        for prefix in ("【待办督战】", "[Todo follow-up]"):
            self.assertTrue(is_own_bot_message({}, prefix + " @海外渠道督战官 确认合同"))

    def test_parser_routine_process_items_are_not_task_only_business_todos(self):
        from app.duzhan_ledger import parse_owner_reports
        from app.duzhan_departments import task_scope_row

        for body in ("客户名单地区德国，今日触达15人，添加WhatsApp7人，邮箱触达8人其中5封退信，有效触达共计10人，暂无回复",
                     "1. 补交MTO和日报", "1. 提交4款MTO方案"):
            with self.subTest(body=body):
                tasks, blockers, evidence = parse_owner_reports(
                    [dict(sender_user_id=12564, body=body, message_type="text", created_at="2026-10-21T01:00:00Z")], 12564)
                self.assertTrue(tasks)
                row = task_scope_row(dict(group=self.group.name, display="刘春梅", collections=tasks, evidence=evidence))
                self.assertEqual(row["collections"], [])
                self.assertEqual(row["evidence"], [])
        for body in ("1. 提交MTO报价给徐豪", "1. 完成MTO报价给客户A"):
            with self.subTest(business=body):
                tasks, _, evidence = parse_owner_reports(
                    [dict(sender_user_id=12564, body=body, message_type="text", created_at="2026-10-21T01:00:00Z")], 12564)
                self.assertTrue(tasks)
                row = task_scope_row(dict(group=self.group.name, display="刘春梅", collections=tasks, evidence=evidence))
                self.assertEqual(row["collections"], tasks)
