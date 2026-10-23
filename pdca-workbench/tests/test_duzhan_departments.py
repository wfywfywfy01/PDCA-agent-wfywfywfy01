"""Department reports use the confirmed cohort, never missing data as zero."""
from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.duzhan import GROUPS, render_brief, render_person_briefs, run_duzhan
from app.duzhan_departments import DEPARTMENTS, member_rows, total


class DepartmentCheckins(TestCase):
    def setUp(self):
        self.group = next(group for group in GROUPS if group.name == "杨晶晶业绩达标群")
        self.now = datetime(2026, 10, 20, 10, tzinfo=ZoneInfo(self.group.tz))
        self.rows = [dict(group=self.group.name, display=name, perf_arrived_wan=value,
                          mto_count=0, mto_quotes=[], history_ok=True, daily_report_ok=True, collections=[])
                     for name, value in (("杨晶晶", 100), ("何海文", 20), ("王宇彤", 5))]
        self.ledger = {"day": "2026-10-20", "people": self.rows}
        self.settings = patch("app.duzhan.get_settings", return_value=SimpleNamespace(duzhan_compact=True))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.weekly = patch("app.weekly_focus.items_for", return_value=[])
        self.weekly.start()
        self.addCleanup(self.weekly.stop)
        self.meeting = patch("app.meeting_todos.items_for_group", return_value=[])
        self.meeting.start()
        self.addCleanup(self.meeting.stop)

    def render(self, hour):
        return render_person_briefs(self.group, hour, self.now.replace(hour=hour), self.ledger)

    def test_exact_department_roster(self):
        self.assertEqual({item.name: item.members for item in DEPARTMENTS}, {
            "经销商一部": ("于冰",), "经销商二部": ("杨晶晶", "何海文", "王宇彤"),
            "经销商三部": ("Lina", "Safae", "冯磊"), "经销商四部": ("尤文静", "Sana", "张月馨"),
            "经销商五部": ("邓琳莹", "刘春梅", "付汪阳"),
        })

    def test_department_preview_uses_full_roster_and_rejects_personal_subset(self):
        import json
        from app.duzhan_admin.service import preview_agent, validate_agent
        from app.models.duzhan_agent import DuzhanAgent

        blocks = [{"type": "group", "channel_id": self.group.channel_id, "label": "自定义群名"},
                  {"type": "times", "slots": ["10:00"]},
                  {"type": "people", "names": ["杨晶晶"]}]
        agent = DuzhanAgent(name="二部", blocks_json=json.dumps({"blocks": blocks}))
        preview = preview_agent(agent)
        self.assertEqual(preview["spec"]["people"], ["杨晶晶", "何海文", "王宇彤"])
        self.assertTrue(any("完整部门名单" in error for error in preview["errors"]))
        self.assertTrue(any("部门成员" in line and "王宇彤" in line for line in preview["summary"]))
        for names in ([], ["杨晶晶", "何海文", "王宇彤"]):
            blocks[2]["names"] = names
            agent.blocks_json = json.dumps({"blocks": blocks})
            self.assertEqual(validate_agent(agent, strategies=[]), [])

    def test_one_report_uses_department_goal_and_all_members(self):
        self.rows[0]["target_wan"] = 1
        parts = self.render(10)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["display"], "")
        text = parts[0]["text"]
        for value in ("经销商二部", "杨晶晶", "何海文", "王宇彤", "800万", "125万", "25.81"):
            self.assertIn(value, text)
        self.assertNotIn("本月1万", text)
        self.assertEqual(text, render_brief(self.group, 10, self.now, self.ledger))

    def test_unknown_member_amount_keeps_the_department_total_pending(self):
        self.rows[2]["perf_arrived_wan"] = None
        text = self.render(10)[0]["text"]
        self.assertIn("待确认", text)
        self.assertIn("王宇彤", text)
        self.assertNotIn("累计已录单120万", text)

    def test_non_finite_aggregate_and_oversized_integer_degrade_to_pending(self):
        for values in ((1e308, 1e308, 0), (10 ** 400, 0, 0)):
            with self.subTest(values=values):
                for row, value in zip(self.rows, values):
                    row["perf_arrived_wan"] = value
                self.assertIsNone(total(list(zip(("杨晶晶", "何海文", "王宇彤"), self.rows)), "perf_arrived_wan"))
                self.assertIn("累计已录单待确认", self.render(10)[0]["text"])

    def test_break_zero_never_becomes_a_numeric_zero_daily_target(self):
        group = next(group for group in GROUPS if group.name == "Q4五百万")
        with patch("app.duzhan_departments._file_target", return_value={"goal": "break_zero", "target_wan": 0}):
            text = render_brief(group, 10, self.now, {"people": [
                dict(group=group.name, display="邓琳莹", perf_arrived_wan=0),
            ]})
        self.assertIn("破零", text)
        self.assertNotIn("今日目标0万", text)

    def test_missing_mto_data_is_not_reported_as_zero_submissions(self):
        self.rows[2]["mto_count"] = None
        text = self.render(20)[0]["text"]
        line = next(line for line in text.splitlines() if line.startswith("MTO核验"))
        self.assertIn("采集数待确认", line)
        self.assertIn("待核：王宇彤", line)

    def test_missing_or_failed_history_provenance_keeps_mto_and_closure_pending(self):
        for state in (None, False):
            with self.subTest(state=state):
                self.rows[0]["history_ok"] = state
                text = self.render(20)[0]["text"]
                mto = next(line for line in text.splitlines() if line.startswith("MTO核验"))
                self.assertIn("采集数待确认", mto)
                self.assertIn("待核：杨晶晶", mto)
                self.assertIn("闭环核对：待确认：杨晶晶", text)

    def test_collection_distinguishes_failed_history_from_successful_empty_history(self):
        from app import duzhan_ledger as dl

        owner = next(item for item in dl.OWNERS if item.display == "杨晶晶")
        for failed in (True, False):
            with self.subTest(failed=failed):
                def fetch(channel, day, limit):
                    return None if failed and channel == "follow" else []

                with patch.object(dl, "OWNERS", (owner,)), \
                     patch.object(dl, "get_settings", return_value=SimpleNamespace(todo_group_channel_id="report")), \
                     patch.object(dl, "fetch_personal_okr", return_value=[]), \
                     patch.object(dl, "load_vps_activity", return_value={}), \
                     patch.object(dl, "fetch_vemory_day", return_value=[]), \
                     patch.object(dl, "load_month_targets", return_value={}), \
                     patch.object(dl, "warn_target_fallback"), \
                     patch.object(dl, "_history_ids", return_value=["main", "follow"]), \
                     patch.object(dl, "fetch_channel_history", side_effect=fetch), \
                     patch.object(dl, "_mcp_bundle", return_value=(None, None, None)), \
                     patch("app.meeting_todos.block_for_group", return_value=""), \
                     patch("app.mto_ocr.review_mto_attachment") as ocr:
                    row = dl.collect_ledger("2026-10-20")["people"][0]
                self.assertEqual(row["history_ok"], not failed)
                if failed:
                    self.assertIsNone(row["mto_count"])
                    ocr.assert_not_called()
                else:
                    self.assertEqual(row["mto_count"], 0)
                    ocr.assert_not_called()

    def test_invalid_history_response_remains_unavailable(self):
        from app.duzhan_ledger import fetch_channel_history

        for payload in (None, {"error": "unavailable"}, {"messages": None}):
            with self.subTest(payload=payload), patch("app.vertu.client.run_vertu_sync_json", return_value=payload):
                self.assertIsNone(fetch_channel_history("channel", "2026-10-20"))
        with patch("app.vertu.client.run_vertu_sync_json", return_value={"messages": []}):
            self.assertEqual(fetch_channel_history("channel", "2026-10-20"), [])

    def test_paris_custom_time_preserves_english_department_and_self_message_guard(self):
        from app.duzhan import is_own_bot_message

        group = next(group for group in GROUPS if group.lang == "en")
        now = datetime(2026, 10, 20, 9, 35, tzinfo=ZoneInfo(group.tz))
        text = render_brief(group, 9, now, minute=35, focus_override="@海外渠道督战官 核对任务")
        for value in ("Dealer Dept 3", "400 wan CNY", "09:35", "Europe/Paris", "Lina", "Safae"):
            self.assertIn(value, text)
        self.assertTrue(is_own_bot_message({}, text))

    def test_non_member_data_does_not_trigger_fifth_department_conditions_or_ai_rule(self):
        import json
        from app.duzhan_admin import ai_rules, runtime
        from app.duzhan_blocks import parse_blocks
        from app.models.duzhan_agent import DuzhanAgent

        group = next(group for group in GROUPS if group.name == "Q4五百万")
        agent = DuzhanAgent(name="五部", blocks_json=json.dumps({"blocks": [
            {"type": "group", "channel_id": group.channel_id, "label": group.name},
            {"type": "condition", "key": "has_data", "value": True},
        ]}))
        ledger = {"people": [dict(group=group.name, display="非本部成员", perf_arrived_wan=100, daily_report_ok=True)]}
        self.assertFalse(runtime.conditions_allow(agent, "2026-10-20", ledger))
        rule = parse_blocks({"blocks": [{"type": "rule", "when": "missing_report", "text": "催日报"}]})[0]
        self.assertFalse(ai_rules._rule_matches(rule, group, "2026-10-20", ledger))
        self.assertNotIn("非本部成员", ai_rules._digest(group, 10, "2026-10-20", ledger))

    def test_early_keeps_daily_weekly_and_joint_owner_tasks(self):
        self.rows[1]["collections"] = [{"title": "客户A尾款", "status": "stalled"}]
        with patch("app.meeting_todos.items_for_group", return_value=[
            {"who": "杨晶晶&何海文", "text": "今天确认交期"},
            {"who": "刘春梅", "text": "不属于本部的任务"},
        ]), patch("app.weekly_focus.items_for", side_effect=lambda day, group, who: [
            {"who": "王宇彤", "text": "本周提交客户B方案"}
        ] if who == "王宇彤" else []):
            text = self.render(10)[0]["text"]
        for value in ("何海文：客户A尾款", "今天确认交期", "本周提交客户B方案", "MTO", "12款", "每人4款"):
            self.assertIn(value, text)
        self.assertNotIn("不属于本部", text)
        self.assertLessEqual(len(text.splitlines()), 8)

    def test_midday_is_one_brief_reminder(self):
        self.rows[0]["collections"] = [{"title": "客户A回款", "status": "planned"}]
        text = self.render(15)[0]["text"]
        self.assertIn("杨晶晶：客户A回款", text)
        self.assertNotIn("MTO", text)
        self.assertNotIn("本周", text)
        self.assertLessEqual(len(text.splitlines()), 4)

    def test_evening_checks_combined_closure_and_preserves_report_fetch_failure(self):
        self.rows[0]["collections"] = [{"title": "客户A尾款", "status": "done", "progress": "已到账"}]
        self.rows[1]["collections"] = [{"title": "客户B合同", "status": "stalled"}]
        self.rows[2]["daily_report_ok"] = False
        text = self.render(20)[0]["text"]
        for value in ("已完成1项", "未闭环1项", "杨晶晶：客户A尾款", "何海文：客户B合同", "王宇彤", "待确认", "明日第一动作"):
            self.assertIn(value, text)

    def test_missing_members_cannot_make_department_closure_look_complete(self):
        del self.rows[1:]
        self.rows[0]["collections"] = [{"title": "客户A尾款", "status": "done"}]
        text = self.render(20)[0]["text"]
        line = next(line for line in text.splitlines() if line.startswith("闭环核对"))
        self.assertIn("待确认", line)
        self.assertIn("何海文", line)
        self.assertIn("王宇彤", line)
        self.assertNotIn("未闭环0项", line)

    def test_missing_process_metrics_are_explicitly_pending_in_evening_report(self):
        text = self.render(20)[0]["text"]
        line = next((line for line in text.splitlines() if line.startswith("成员合计")), "")
        self.assertIn("WhatsApp", line)
        self.assertIn("待确认", line)

    def test_whatsapp_aggregate_preserves_lower_bound_in_both_languages(self):
        for group in (self.group, next(group for group in GROUPS if group.lang == "en")):
            department = next(item for item in DEPARTMENTS if item.group == group.name)
            ledger = {"people": [dict(group=group.name, display=name, perf_arrived_wan=1,
                                      wa_reached=5, wa_lower_bound=index == 0)
                                 for index, name in enumerate(department.members)]}
            text = render_brief(group, 20, self.now, ledger)
            self.assertIn("synced lower bound" if group.lang == "en" else "已同步下限", text)

    def test_mto_captured_quotes_and_qualified_count_are_distinct(self):
        self.rows[0]["mto_count"] = 0
        self.rows[0]["mto_quotes"] = [dict(wan=20, qualifies=False, raw_ok=True) for _ in range(4)]
        line = next(line for line in self.render(20)[0]["text"].splitlines() if line.startswith("MTO核验"))
        self.assertIn("采集数4条", line)
        self.assertIn("已核达标0款", line)

    def test_mto_unread_amount_or_incomplete_qualification_stays_pending(self):
        for count, quotes in ((0, [dict(wan=None, qualifies=False, raw_ok=True)] * 4),
                              (4, [dict(wan=40, qualifies=True)] * 3),
                              (0, [dict(wan=40)] * 4)):
            with self.subTest(count=count, quotes=quotes):
                self.rows[0].update(mto_count=count, mto_quotes=quotes)
                line = next(line for line in self.render(20)[0]["text"].splitlines() if line.startswith("MTO核验"))
                self.assertIn("待核：杨晶晶", line)

    def test_fifth_department_includes_task_only_members_without_mto_quotas(self):
        group = next(group for group in GROUPS if group.name == "Q4五百万")
        ledger = {"people": [dict(group=group.name, display="刘春梅", perf_arrived_wan=7),
                             dict(group=group.name, display="付汪阳", perf_arrived_wan=4),
                             dict(group=group.name, display="邓琳莹", perf_arrived_wan=0)]}
        text = render_brief(group, 10, self.now, ledger)
        self.assertIn("经销商五部", text)
        self.assertIn("破零", text)
        self.assertIn("刘春梅", text)
        self.assertIn("付汪阳", text)
        self.assertIn("累计已录单11万", text)
        self.assertIn("MTO计划：共4款", text)
        self.assertNotIn("0万/天", text)

    def test_fourth_department_matches_existing_viki_and_jiangxu_aliases(self):
        dept = next(item for item in DEPARTMENTS if item.name == "经销商四部")
        ledger = {"people": [dict(group=dept.group, display=name, perf_arrived_wan=amount)
                             for name, amount in (("Viki", 10), ("江旭", 20), ("张月馨", 3))]}
        rows = member_rows(dept, ledger)
        self.assertEqual([name for name, row in rows], ["尤文静", "Sana", "张月馨"])
        self.assertEqual(total(rows, "perf_arrived_wan"), 33)
        ledger["people"].append(dict(group="其他群", display="Viki", perf_arrived_wan=999))
        self.assertEqual(total(member_rows(dept, ledger), "perf_arrived_wan"), 33)

    def test_old_person_snapshot_is_rerendered_as_one_department_message(self):
        snapshot = {"ledger": self.ledger, "person_messages": {self.group.channel_id: [
            {"display": row["display"], "text": "旧的逐人正文"} for row in self.rows
        ]}}
        with patch("app.duzhan.load_prepared", return_value=snapshot), patch(
            "app.duzhan.groups_for_tz", return_value=[self.group]
        ), patch("app.duzhan._previous_prepared_for_group", return_value=None), patch(
            "app.duzhan_admin.runtime.using_db", return_value=False
        ), patch("app.duzhan.push_duzhan_message", return_value=True) as push:
            result = run_duzhan(self.group.tz, 10, self.now)
        self.assertEqual(push.call_count, 1)
        self.assertIn("经销商二部", push.call_args.args[0])
        self.assertNotIn("旧的逐人正文", push.call_args.args[0])
        self.assertTrue(result["from_snapshot"])


class DepartmentCardConfiguration(TestCase):
    def test_apply_is_idempotent_and_keeps_times_rules_and_pause_state(self):
        import json
        from sqlmodel import Session, SQLModel, create_engine, select
        from app.duzhan_admin import service
        from app.models.duzhan_agent import DuzhanAgent

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            for group in GROUPS:
                blocks = {"blocks": [
                    {"type": "group", "channel_id": group.channel_id, "label": group.name},
                    {"type": "times", "slots": ["09:35", "14:35", "19:35"]},
                    {"type": "people", "names": ["旧成员"]},
                    {"type": "rule", "mode": "text", "text": "原有文案", "when": "always"},
                    {"type": "style", "lang": group.lang},
                ]}
                session.add(DuzhanAgent(name=group.name + "督战官", enabled=group.lang != "en",
                                       timezone=group.tz, blocks_json=json.dumps(blocks, ensure_ascii=False)))
            session.add(DuzhanAgent(name="某人C转B", enabled=False, blocks_json='{"blocks":[]}'))
            session.commit()
            self.assertEqual(len(service.configure_departments(session, apply=False)), 5)
            self.assertEqual(len(service.configure_departments(session, apply=True)), 5)
            self.assertEqual(service.configure_departments(session, apply=True), [])
            cards = session.exec(select(DuzhanAgent)).all()
            for department in DEPARTMENTS:
                card = next(row for row in cards if row.name == department.name + "督战官")
                blocks = json.loads(card.blocks_json)["blocks"]
                self.assertEqual(next(row["names"] for row in blocks if row["type"] == "people"), list(department.members))
                self.assertEqual(next(row["slots"] for row in blocks if row["type"] == "times"), ["09:35", "14:35", "19:35"])
                self.assertEqual(next(row["text"] for row in blocks if row["type"] == "rule"), "原有文案")
            self.assertFalse(next(row for row in cards if row.name == "经销商三部督战官").enabled)
            self.assertFalse(next(row for row in cards if row.name == "某人C转B").enabled)
