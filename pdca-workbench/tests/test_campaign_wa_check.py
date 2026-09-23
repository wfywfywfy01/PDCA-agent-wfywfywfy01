# -*- coding: utf-8 -*-
"""腕表闪购 WhatsApp 核查：每天 08:00 出一次（前 24 小时），交付与其他早报同一套。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import wa_campaign_check


def _fake_mcp(name: str, arguments: dict, timeout: float = 180.0) -> dict:
    """假 MCP：命中“mechanical”的人给一条消息，其余返回空。"""
    keyword = str(arguments.get("keyword") or "")
    employee_id = (arguments.get("subject") or {}).get("employee_id")
    if name == "business.query":
        if employee_id == 238:
            return {
                "rows": [
                    {
                        "row_type": "summary",
                        "reached_customer_count": 19,
                        "replied_customer_count": 15,
                        "outbound_message_count": 60,
                        "inbound_message_count": 30,
                        "platform_metrics": {"whatsapp": {"included": True, "reached_customer_count": 19}},
                        "data_freshness": {"overall_status": "complete"},
                    }
                ]
            }
        return {"rows": []}
    if employee_id == 238 and keyword in ("mechanical", "机械", "42,000", "allocation"):
        return {
            "rows": [
                {
                    "row_type": "detail",
                    "id": "wa_test_1",
                    "time": "2026-09-19 10:00:00",
                    "direction": "outbound",
                    "customer_display": "601***1111",
                    "content": "Mechanical watch allocation: order 42,000 USD confirms 1 watch today",
                }
            ]
        }
    return {"rows": []}


class CampaignCheckTests(unittest.TestCase):
    def test_run_writes_html_and_json(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "app.wa_campaign_check._script_module"
        ) as loader:
            module = mock.MagicMock()
            module.TARGETS = (("何海文", 238),)
            module.fetch_hits = lambda display, eid, start, end: {
                "display": display,
                "employee_id": eid,
                "hits": [
                    {
                        "id": "wa_test_1",
                        "time": "2026-09-19 10:00:00",
                        "direction": "outbound",
                        "customer": "601***1111",
                        "content": "Mechanical watch allocation 42,000 USD",
                        "themes": ["机械腕表", "门槛 4.2 万美元", "配给/配货"],
                        "keywords": ["mechanical"],
                    }
                ],
                "themes": {"机械腕表": ["wa_test_1"], "门槛 4.2 万美元": ["wa_test_1"], "配给/配货": ["wa_test_1"]},
                "errors": [],
            }
            module.fetch_baseline = lambda eid, start, end: {"reached": 19, "replied": 15, "outbound": 60, "inbound": 30}
            module.judge = lambda person: ("明确传达了活动", "good")
            module.render = lambda payload: "<html>核查</html>"
            module.run = lambda days=2, end="", posters_dir="", out="": {
                "html": out,
                "json": str(Path(out).with_suffix(".json")),
                "summary": {"period": ["2026-09-18", "2026-09-19"], "people": [{"display": "何海文", "verdict": "明确传达了活动", "hits": 1, "themes": ["机械腕表"]}]},
                "bytes": 12,
            }
            loader.return_value = module
            result = wa_campaign_check.run_check(Path(tmp) / "campaign_wa", days=2, end="2026-09-19")
        self.assertTrue(str(result["html"]).endswith("机械腕表闪购_WhatsApp核查_2026-09-19.html"))
        self.assertEqual(result["summary"]["period"], ["2026-09-18", "2026-09-19"])


class VerdictWithMediaTests(unittest.TestCase):
    """图片素材也要进判定（老板 2026-09-20：于冰其实发了，文本扫描抓不到图）。"""

    def _person(self, **over: object) -> dict:
        person = {"display": "x", "hits": [], "themes": {}, "media": []}
        person.update(over)
        return person

    def _script(self):
        """judge() 在 scripts/wa_campaign_check.py 里，通过 bridge 的加载器取。"""
        from app.wa_campaign_check import _script_module

        return _script_module()

    def test_mechanical_poster_image_counts_as_delivered(self):
        person = self._person(
            media=[{"kind": "机械腕表配给", "text": "MECHANICAL WATCH ALLOCATION TODAY ONLY"}]
        )
        self.assertEqual(self._script().judge(person)[0], "明确传达了活动（含图片素材）")

    def test_watch_clearance_image_is_not_the_allocation_campaign(self):
        person = self._person(
            hits=[
                {
                    "id": "1",
                    "time": "2026-09-18 10:42:21",
                    "direction": "outbound",
                    "customer": "849***8004",
                    "content": "Good day Mr. Watcharaphon",
                    "themes": ["腕表/表"],
                    "keywords": ["watch"],
                }
            ],
            media=[{"kind": "腕表清仓", "text": "VERTU CLEARANCE - TIMEPIECES / WATCH H1"}],
        )
        verdict = self._script().judge(person)[0]
        self.assertIn("腕表素材", verdict)
        self.assertIn("不是 TODAY ONLY 配给", verdict)

    def test_text_verdict_still_works(self):
        person = self._person(
            hits=[{"id": "1", "time": "", "direction": "outbound", "customer": "x", "content": "机械腕表配给 30 万", "themes": ["机械腕表", "配给/配货", "门槛 30 万人民币"], "keywords": ["机械"]}],
            themes={"机械腕表": ["1"], "配给/配货": ["1"], "门槛 30 万人民币": ["1"]},
        )
        self.assertEqual(self._script().judge(person)[0], "明确传达了活动（文字）")


class CampaignJobTests(unittest.TestCase):
    def _register(self, **over: object):
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
            "daily_digest_enabled": False,
            "evidence_report_enabled": False,
            "campaign_wa_check_enabled": True,
            "campaign_wa_check_time": "08:00",
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
        return {
            kwargs["id"]: (kwargs["hour"], kwargs["minute"])
            for _, _, kwargs in scheduler.jobs
            if str(kwargs.get("id", "")).startswith("campaign_wa_check")
        }

    def test_registered_at_0800_with_backup(self):
        slots = self._register()
        self.assertEqual(slots["campaign_wa_check"], (8, 0))
        self.assertEqual(slots["campaign_wa_check_backup"], (8, 30))

    def test_disabled_registers_nothing(self):
        self.assertEqual(self._register(campaign_wa_check_enabled=False), {})

    def test_job_sends_via_shared_sender(self):
        """08:00 任务：生成 → 用共享发送器发给共享名单；失败要告警。"""
        from app.scheduler import jobs as scheduler_jobs

        settings = SimpleNamespace(
            data_dir=Path(tempfile.mkdtemp()),
            campaign_wa_check_days=2,
            campaign_wa_check_user_ids=[],
            campaign_wa_check_channel_id="",
            mgmt_html_user_ids=[13365, 13102, 12564],
            duzhan_bot_app_id="vbot",
            todo_bot_app_id="",
        )
        sent: list[list[str]] = []

        def fake_run(args, timeout=None):
            sent.append(args)
            return 0, "{}", ""

        fake_result = {
            "html": str(Path(settings.data_dir) / "x.html"),
            "json": "",
            "bytes": 100,
            "summary": {
                "period": ["2026-09-18", "2026-09-19"],
                "people": [
                    {"display": "何海文", "verdict": "明确传达了活动", "hits": 5, "themes": []},
                    {"display": "于冰", "verdict": "只提到表/表字，未涉及活动", "hits": 5, "themes": []},
                ],
            },
        }
        Path(fake_result["html"]).write_text("<html>x</html>", encoding="utf-8")
        with mock.patch.object(
            scheduler_jobs, "get_settings", return_value=settings
        ), mock.patch(
            "app.scheduler.run_ledger.claim_run", return_value=True
        ), mock.patch(
            "app.scheduler.run_ledger.finish_run"
        ), mock.patch(
            "app.strategy_wa_brief.run_report", return_value=fake_result
        ), mock.patch(
            "app.config.get_settings", return_value=settings
        ), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            scheduler_jobs.campaign_wa_check_job()
        self.assertEqual(len(sent), 3, "共享名单三个人都要发")
        self.assertEqual(len({call[2] for call in sent}), 1, "都发到同一个 user-id 位置")

    def test_job_sends_to_group_when_configured(self):
        """配了管理群就只发群：一条群消息，不再私发共享名单。"""
        from app.scheduler import jobs as scheduler_jobs

        settings = SimpleNamespace(
            data_dir=Path(tempfile.mkdtemp()),
            campaign_wa_check_days=2,
            campaign_wa_check_user_ids=[],
            campaign_wa_check_channel_id="chan-mgmt",
            mgmt_html_user_ids=[13365, 13102, 12564],
            duzhan_bot_app_id="vbot",
            todo_bot_app_id="",
        )
        sent: list[list[str]] = []

        def fake_run(args, timeout=None):
            sent.append(args)
            return 0, "{}", ""

        html = Path(settings.data_dir) / "x.html"
        html.write_text("<html>x</html>", encoding="utf-8")
        with mock.patch.object(
            scheduler_jobs, "get_settings", return_value=settings
        ), mock.patch(
            "app.scheduler.run_ledger.claim_run", return_value=True
        ), mock.patch(
            "app.scheduler.run_ledger.finish_run"
        ), mock.patch(
            "app.strategy_wa_brief.run_report",
            return_value={"html": str(html), "body": "正文"},
        ), mock.patch(
            "app.config.get_settings", return_value=settings
        ), mock.patch(
            "app.vertu.client.run_vertu_sync", side_effect=fake_run
        ):
            scheduler_jobs.campaign_wa_check_job()
        self.assertEqual(len(sent), 1, "只发一条群消息")
        self.assertIn("+send", sent[0])
        self.assertIn("chan-mgmt", sent[0])

    def test_send_failure_is_failed_so_backup_can_retry(self):
        """发出去失败必须记 failed，08:30 同一天台账才会再认领。"""
        from app.scheduler import jobs as scheduler_jobs

        settings = SimpleNamespace(
            data_dir=Path(tempfile.mkdtemp()),
            campaign_wa_check_user_ids=[13102],
            campaign_wa_check_channel_id="",
            mgmt_html_user_ids=[],
            duzhan_bot_app_id="vbot",
            todo_bot_app_id="",
        )
        html = Path(settings.data_dir) / "x.html"
        html.write_text("<html>x</html>", encoding="utf-8")
        finishes: list[tuple] = []

        def finish(*args, **kwargs):
            finishes.append(args)

        with mock.patch.object(
            scheduler_jobs, "get_settings", return_value=settings
        ), mock.patch(
            "app.scheduler.run_ledger.claim_run", return_value=True
        ), mock.patch(
            "app.scheduler.run_ledger.finish_run", side_effect=finish
        ), mock.patch(
            "app.strategy_wa_brief.run_report",
            return_value={"html": str(html), "body": "策略核查"},
        ), mock.patch(
            "app.config.get_settings", return_value=settings
        ), mock.patch(
            "app.vertu.client.run_vertu_sync", return_value=(1, "", "network")
        ), mock.patch(
            "app.scheduler.jobs.notify"
        ):
            scheduler_jobs.campaign_wa_check_job()
        self.assertTrue(finishes)
        self.assertEqual(finishes[-1][2], "failed")


if __name__ == "__main__":
    unittest.main()