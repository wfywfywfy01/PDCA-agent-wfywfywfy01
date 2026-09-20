# -*- coding: utf-8 -*-
"""2026-09-20 审查修复的回归用例（噪声正则 / 幂等键 / 附件名 / claim 重试 / 工时口径）。"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from app.duzhan_ledger import _PERF_NOISE_RE, estimate_hours, parse_performance_buckets


class NoiseRegexTests(unittest.TestCase):
    """审查 P1：正则里的 \\s 曾被写成字面 s，空白容错失效。"""

    def test_whitespace_variants_are_filtered(self):
        for text in ("水单（无）", "水单 （无）", "水单（ 无 ）", "意向 （无）", "无 VPS 留痕", "无VPS留痕",
                     "20:00 [晚追]：无 VPS 留痕记录"):
            self.assertTrue(_PERF_NOISE_RE.search(text), text)

    def test_bucket_parser_drops_template_echo(self):
        msgs = [
            {"sender_user_id": 1, "message_type": "text", "body": "水单 （无）", "created_at": "2026-09-19T02:00:00Z"},
            {"sender_user_id": 1, "message_type": "text", "body": "意向（ 无 ）", "created_at": "2026-09-19T02:01:00Z"},
        ]
        buckets = parse_performance_buckets(msgs, 1)
        self.assertEqual(buckets["slip"], [])
        self.assertEqual(buckets["intent"], [])


class HoursSemanticsTests(unittest.TestCase):
    """审查 P2：零证据时工时是「没出数」而不是「0 小时」。"""

    def test_no_evidence_returns_none(self):
        est = estimate_hours([], {})
        self.assertIsNone(est["minutes"])
        self.assertEqual(est["band"], "待确认")

    def test_real_zero_still_zero(self):
        est = estimate_hours([{"outbound": 0, "inbound": 0, "last": ""}], {"mto_count": 0})
        self.assertIsNotNone(est["minutes"])


class IdempotencyNamespaceTests(unittest.TestCase):
    """审查 P0：Agent 草稿与确定性三追推送不能共用同一个幂等键。"""

    def test_agent_and_duzhan_keys_differ(self):
        from app.duzhan import _idempotency_key

        duzhan_key = _idempotency_key("Asia/Shanghai", "2026-09-20", 20, "chan-1234")
        agent_key = _idempotency_key("Asia/Shanghai", "2026-09-20", 20, "chan-1234", producer="agent")
        self.assertNotEqual(duzhan_key, agent_key)
        self.assertTrue(duzhan_key.startswith("duzhan-"))
        self.assertTrue(agent_key.startswith("agent-"))


class AttachmentNameTests(unittest.TestCase):
    """审查 P2：附件名要净化，防路径穿越。"""

    def test_traversal_is_stripped(self):
        from app.evidence_report import _safe_attachment_name

        cleaned = _safe_attachment_name("..\\..\\evil.png", 3)
        self.assertNotIn("..", cleaned)
        self.assertNotIn("/", cleaned)
        self.assertNotIn("\\", cleaned)
        self.assertTrue(cleaned.endswith("evil.png"))

    def test_download_cleans_temp_dir(self):
        import tempfile
        from pathlib import Path

        from app import evidence_report

        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def fake_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(path)
            return path

        with mock.patch("tempfile.mkdtemp", side_effect=fake_mkdtemp), mock.patch(
            "app.vertu.client.run_vertu_sync", return_value=(1, "", "fail")
        ):
            evidence_report.download_images([{"display": "x"}], {"x": []}, 1)
        self.assertTrue(created)
        for path in created:
            self.assertFalse(Path(path).exists(), "临时目录必须回收")


class ClaimRetryTests(unittest.TestCase):
    """审查 P1：failed 允许兜底触发重试（重复外发由幂等键兜住）。"""

    def test_failed_can_be_reclaimed(self):
        from datetime import datetime, timezone

        from app.models.scheduled_job_run import ScheduledJobRun
        from app.scheduler import run_ledger

        row = ScheduledJobRun(
            run_key="duzhan:test", job_name="duzhan", bucket="test", status="failed",
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def exec(self, _stmt):
                class Result:
                    def first(self_inner):
                        return row

                return Result()

            def add(self, _obj):
                return None

            def commit(self):
                return None

        with mock.patch("app.scheduler.run_ledger.Session", lambda *a, **k: FakeSession()):
            self.assertTrue(run_ledger.claim_run("duzhan", "test"))
        self.assertEqual(row.status, "sending")

    def test_sent_still_blocked(self):
        from datetime import datetime, timezone

        from app.models.scheduled_job_run import ScheduledJobRun
        from app.scheduler import run_ledger

        row = ScheduledJobRun(
            run_key="duzhan:test2", job_name="duzhan", bucket="test2", status="sent",
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def exec(self, _stmt):
                class Result:
                    def first(self_inner):
                        return row

                return Result()

            def add(self, _obj):
                return None

            def commit(self):
                return None

        with mock.patch("app.scheduler.run_ledger.Session", lambda *a, **k: FakeSession()):
            self.assertFalse(run_ledger.claim_run("duzhan", "test2"))




class ParallelCollectTests(unittest.TestCase):
    """审查：采集全是 I/O，改成并发后必须保持顺序、且单项异常不能拖垮整轮。"""

    def test_order_preserved_and_error_isolated(self):
        from app.duzhan_ledger import _parallel_map

        def fn(item):
            if item == "bad":
                raise RuntimeError("boom")
            return item.upper()

        self.assertEqual(_parallel_map(fn, ["a", "bad", "c"], 3, "test"), ["A", None, "C"])
        self.assertEqual(_parallel_map(fn, [], 4, "test"), [])
        self.assertEqual(_parallel_map(fn, ["a"], 4, "test"), ["A"])

    def test_workers_are_clamped_to_item_count(self):
        from app.duzhan_ledger import _parallel_map

        seen: list[int] = []

        def fn(item):
            seen.append(item)
            return item

        self.assertEqual(_parallel_map(fn, [1, 2], 8, "test"), [1, 2])
        self.assertEqual(sorted(seen), [1, 2])


class MonthlyTargetSourceTests(unittest.TestCase):
    """月目标单一来源：目标文件优先（用户每月更新），缺条目才回退硬编码并告警。"""

    def _owner(self, display: str):
        from app.duzhan_ledger import OWNERS

        return next(item for item in OWNERS if item.display == display)

    def test_file_wins_over_hardcoded(self):
        from app.duzhan_ledger import resolve_month_target

        self.assertEqual(
            resolve_month_target(self._owner("于冰"), "2026-09-18", {"于冰": 500}),
            (500, "file"),
        )

    def test_hardcoded_is_last_resort(self):
        from app.duzhan_ledger import resolve_month_target

        self.assertEqual(
            resolve_month_target(self._owner("于冰"), "2026-09-18", {}),
            (200, "hardcoded"),
        )

    def test_english_display_falls_back_to_target_name(self):
        from app.duzhan_ledger import resolve_month_target

        # 台账显示名是 Viki，目标文件里写的是 尤文静
        self.assertEqual(
            resolve_month_target(self._owner("Viki"), "2026-09-18", {"尤文静": 120}),
            (120, "file"),
        )

    def test_newcomer_gets_group_split(self):
        from app.duzhan_ledger import load_month_targets, resolve_month_target

        targets = load_month_targets("2026-09-18")
        value, source = resolve_month_target(self._owner("江旭"), "2026-09-18", targets)
        self.assertEqual(source, "group")
        self.assertAlmostEqual(value, 20.0, places=2)

    def test_scope_flags_unconfigured_month(self):
        from app.duzhan_ledger import load_month_targets, month_target_scope

        covered, missing = month_target_scope("2026-09-18", load_month_targets("2026-09-18"))
        self.assertTrue(covered, f"当月目标文件应覆盖全员，缺: {missing}")
        covered, missing = month_target_scope("2026-10-02", {})
        self.assertFalse(covered)
        self.assertIn("于冰", missing)

    def test_warn_once_per_month_and_silent_when_covered(self):
        from app import duzhan_ledger as dl

        dl._TARGET_WARNED.clear()
        sent: list = []
        try:
            with mock.patch("app.duzhan_ledger.notify", side_effect=lambda *a, **k: sent.append(a)):
                dl.warn_target_fallback("2026-09-18", dl.load_month_targets("2026-09-18"))
                self.assertEqual(sent, [], "文件覆盖时不该告警")
                self.assertIn("于冰", dl.warn_target_fallback("2026-11-03", {}))
                dl.warn_target_fallback("2026-11-04", {})
        finally:
            dl._TARGET_WARNED.clear()
        self.assertEqual(len(sent), 1, "同一个月只告警一次")


class TlsVerifyTests(unittest.TestCase):
    """审查：Qwen 网关证书由公共 CA 签发，禁止再用 verify=False 关掉校验。"""

    def test_default_is_standard_verification(self):
        from app import mto_ocr

        fake = mock.Mock(qwen_ca_bundle="")
        with mock.patch.object(mto_ocr, "get_settings", lambda: fake):
            self.assertIs(mto_ocr._tls_verify(), True)

    def test_ca_bundle_is_used_when_configured(self):
        from app import mto_ocr

        fake = mock.Mock(qwen_ca_bundle="/etc/ssl/certs/intranet-ca.pem")
        with mock.patch.object(mto_ocr, "get_settings", lambda: fake):
            self.assertEqual(mto_ocr._tls_verify(), "/etc/ssl/certs/intranet-ca.pem")

    def test_source_has_no_verify_false(self):
        from pathlib import Path

        from app import mto_ocr

        source = Path(mto_ocr.__file__).read_text(encoding="utf-8")
        # 只查真正的调用实参（文档里会提到这个写法，不能误伤）
        self.assertIsNone(re.search(r"verify\s*=\s*False\s*[,)]", source))


class MtoOcrWorkerSettingTests(unittest.TestCase):
    """OCR 并发度可配（Qwen 单机推理，默认只给 2）。"""

    def _workers(self):
        import os

        from app.config import Settings

        with mock.patch.dict(os.environ, {"PDCA_MTO_OCR_WORKERS": "3"}, clear=False):
            self.assertEqual(Settings().mto_ocr_workers, 3)
        with mock.patch.dict(os.environ, {"PDCA_MTO_OCR_WORKERS": "0"}, clear=False):
            self.assertEqual(Settings().mto_ocr_workers, 1)
        with mock.patch.dict(os.environ, {"PDCA_MTO_OCR_WORKERS": "abc"}, clear=False):
            self.assertEqual(Settings().mto_ocr_workers, 3)

    def test_env_parsing(self):
        self._workers()


class SetMonthlyTargetsScriptTests(unittest.TestCase):
    """月度目标维护脚本：合并保留原顺序，坏入参直接拒绝。"""

    def _module(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "scripts" / "set_monthly_targets.py"
        spec = importlib.util.spec_from_file_location("set_monthly_targets", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_merge_keeps_order_and_updates(self):
        module = self._module()
        entries = [
            {"name": "于冰", "target_wan": 200},
            {"name": "新部", "target_wan": 100, "members": ["邓琳莹"]},
        ]
        merged = module.merge(
            entries,
            [("于冰", 260), ("Lina", 400)],
            [{"name": "新部", "target_wan": 120, "members": ["邓琳莹", "江旭"]}],
        )
        self.assertEqual([item["name"] for item in merged], ["于冰", "新部", "Lina"])
        self.assertEqual(merged[0]["target_wan"], 260)
        self.assertEqual(merged[1]["members"], ["邓琳莹", "江旭"])

    def test_bad_input_is_rejected(self):
        module = self._module()
        self.assertEqual(module.parse_person(" 于冰 = 200 "), ("于冰", 200))
        with self.assertRaises(SystemExit):
            module.parse_person("于冰")
        with self.assertRaises(SystemExit):
            module.parse_person("于冰=abc")
        with self.assertRaises(SystemExit):
            module.parse_group("新部=100")

    def test_dry_run_writes_nothing(self):
        import json
        import tempfile
        from pathlib import Path

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(json.dumps({"2026-09": {"entries": [{"name": "于冰", "target_wan": 200}]}}), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            module.main(["--month", "2026-10", "--copy-from", "2026-09", "--dry-run", "--file", str(path)])
            self.assertEqual(path.read_text(encoding="utf-8"), before, "dry-run 不能落盘")

    def test_mismatch_with_department_total_is_rejected(self):
        import json
        import tempfile
        from pathlib import Path

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(
                json.dumps({"2026-09": {"department_target_wan": 300, "entries": [{"name": "于冰", "target_wan": 300}]}}),
                encoding="utf-8",
            )
            before = path.read_text(encoding="utf-8")
            with self.assertRaises(SystemExit):
                module.main(
                    ["--month", "2026-10", "--copy-from", "2026-09", "--person", "于冰=400", "--file", str(path)]
                )
            self.assertEqual(path.read_text(encoding="utf-8"), before, "合计不一致时不能落盘")
            module.main(["--month", "2026-10", "--copy-from", "2026-09", "--file", str(path)])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["2026-10"]["department_target_wan"], 300)

    def test_write_creates_month_block(self):
        import json
        import tempfile
        from pathlib import Path

        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            path.write_text(
                json.dumps({"2026-09": {"department_target_wan": 1228, "entries": [{"name": "于冰", "target_wan": 200}]}}),
                encoding="utf-8",
            )
            module.main(
                [
                    "--month", "2026-10", "--copy-from", "2026-09",
                    "--dept", "260", "--person", "于冰=260", "--file", str(path),
                ]
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["2026-10"]["entries"][0]["target_wan"], 260)
            self.assertEqual(saved["2026-10"]["department_target_wan"], 260)
            self.assertEqual(saved["2026-09"]["entries"][0]["target_wan"], 200, "旧月份不能被改")


class CollectLedgerWiringTests(unittest.TestCase):
    """并发改造后的接线：源顺序不能错位，每人 MCP/OCR 结果必须按人对上号。"""

    def test_sources_and_per_person_caches_line_up(self):
        from app import duzhan_ledger as dl

        history_calls: list[tuple] = []

        def fake_history(channel_id, day, size):
            history_calls.append((channel_id, size))
            return []

        def fake_bundle(subject, period):
            key = subject.get("employee_id")
            return (f"reach-{key}", f"ops-{key}", f"customers-{key}")

        def fake_ocr(messages, sender_id, **kwargs):
            return (sender_id, [f"img-{sender_id}"], [])

        okr_rows = [{"salesperson": "于冰", "sales_amount": 2_000_000}]
        vemory_rows = [{"name": "于冰", "meetings": 2}]
        vps_payload = {"sent": 7}

        def fake_vps(owner, activity):
            return (activity.get("sent"), None, "", "", None, False)

        with mock.patch.object(dl, "fetch_personal_okr", lambda: okr_rows), mock.patch.object(
            dl, "load_vps_activity", lambda: vps_payload
        ), mock.patch.object(
            dl, "_vps_for_owner", fake_vps
        ), mock.patch.object(dl, "fetch_vemory_day", lambda day: vemory_rows), mock.patch.object(
            dl, "fetch_channel_history", fake_history
        ), mock.patch.object(dl, "_mcp_bundle", fake_bundle), mock.patch.object(
            dl, "parse_wa_reached", lambda payload: (payload, False)
        ), mock.patch.object(
            dl, "parse_intent_count", lambda payload: payload
        ), mock.patch.object(
            dl, "parse_wa_hour_chats", lambda payload: []
        ), mock.patch(
            "app.mto_ocr.review_mto_images", fake_ocr
        ):
            ledger = dl.collect_ledger("2026-09-18")

        rows = {row["display"]: row for row in ledger["people"]}
        self.assertIn("于冰", rows)
        # 每人 MCP 三项按人对上号（缓存 keyed by display，不能串号）
        for owner in dl.OWNERS:
            if not owner.employee_id:
                continue
            row = rows.get(owner.display)
            self.assertIsNotNone(row, owner.display)
            self.assertEqual(row["wa_reached"], f"reach-{owner.employee_id}", owner.display)
            self.assertEqual(row["intent_count"], f"ops-{owner.employee_id}", owner.display)
        # OCR 结果按人对上号
        self.assertEqual(rows["于冰"]["mto_count"], 13063)
        self.assertEqual(rows["于冰"]["mto_names"], ["img-13063"])
        # 群历史：日报群用 300，个人群用 200；每个群只拉一次
        sizes = {size for _, size in history_calls}
        self.assertEqual(sizes, {"200", "300"})
        self.assertEqual(len(history_calls), len(set(history_calls)))
        # 四个源的数据必须各就各位（按名字取值，不靠下标顺序）
        self.assertEqual(rows["于冰"]["mtd_wan"], 200.0, "personal-okr 应进业绩字段")
        self.assertEqual(rows["于冰"]["vps_im_sent"], 7, "Agent/IM 报告应进 VPS 字段")
        self.assertIsNotNone(rows["于冰"]["vemory"], "Vemory 应进 Vemory 字段")
        self.assertEqual(rows["于冰"]["daily_report"], {}, "日报群数据应进日报字段")
        # 月目标来源应标注为文件（2026-09 已配置）+ 滚动日目标已算
        self.assertEqual(rows["于冰"]["target_source"], "file")
        self.assertIsNotNone(rows["于冰"]["rolling_target_wan"])


class OcrBudgetTests(unittest.TestCase):
    """OCR 限流：超预算/超每人上限按「待确认」处理，绝不拖过整点推送窗口。"""

    def test_deadline_marks_unfinished_as_pending(self):
        import time as _time

        from app.duzhan_ledger import _parallel_map_deadline

        def fn(item):
            if item == "slow":
                _time.sleep(3)
            return item

        start = _time.monotonic()
        results = _parallel_map_deadline(fn, ["a", "slow", "b"], 3, "test", 1)
        cost = _time.monotonic() - start
        self.assertEqual(results[0], "a")
        self.assertIsNone(results[1], "超预算的项必须写待确认")
        self.assertEqual(results[2], "b")
        self.assertLess(cost, 2.5, "不能等没跑完的项")

    def test_zero_budget_means_no_limit(self):
        from app.duzhan_ledger import _parallel_map_deadline

        self.assertEqual(_parallel_map_deadline(lambda x: x * 2, [1, 2], 2, "t", 0), [2, 4])
        self.assertEqual(_parallel_map_deadline(lambda x: x, [], 2, "t", 5), [])

    def test_review_caps_images_per_person(self):
        from app import mto_ocr

        messages = [
            {
                "sender_user_id": 7,
                "message_type": "image",
                "attachments": [{"attachment_type": "image", "url": f"/f/{index}.jpg"}],
            }
            for index in range(5)
        ]
        calls: list[str] = []

        def fake_ocr(url):
            calls.append(url)
            return {"model": "", "wan": None, "usd": None, "qualifies": False}

        settings = mock.Mock(qwen_api_key="k", mto_ocr_max_images=2)
        with mock.patch.object(mto_ocr, "download_ocr_delete", fake_ocr), mock.patch.object(
            mto_ocr, "get_settings", lambda: settings
        ), mock.patch.object(
            mto_ocr, "summarize_quotes", lambda quotes: (len(quotes), [])
        ):
            count, _names, quotes = mto_ocr.review_mto_images(messages, 7)
        self.assertEqual(len(calls), 2, "每人最多 OCR 上限张数")
        self.assertEqual(count, 2)
        self.assertEqual(len(quotes), 2)

    def test_explicit_max_images_wins(self):
        from app import mto_ocr

        messages = [
            {
                "sender_user_id": 7,
                "message_type": "image",
                "attachments": [{"attachment_type": "image", "url": f"/f/{index}.jpg"}],
            }
            for index in range(4)
        ]
        calls: list[str] = []
        settings = mock.Mock(qwen_api_key="k", mto_ocr_max_images=9)
        with mock.patch.object(
            mto_ocr, "download_ocr_delete", lambda url: calls.append(url) or {"qualifies": False}
        ), mock.patch.object(mto_ocr, "get_settings", lambda: settings), mock.patch.object(
            mto_ocr, "summarize_quotes", lambda quotes: (0, [])
        ):
            mto_ocr.review_mto_images(messages, 7, max_images=3)
        self.assertEqual(len(calls), 3)


class AmountParsingTests(unittest.TestCase):
    """审查修复：金额千分位、大数科学计数法（推送里出现过「0万」）。"""

    def test_thousand_separators(self):
        from app.duzhan_ledger import _amount_text, _perf_amount

        self.assertEqual(_perf_amount("水单 1,000万 已付")["wan"], 1000.0)
        self.assertEqual(_perf_amount("意向 1,234.5万")["wan"], 1234.5)
        self.assertEqual(_perf_amount("货款 2,000,000元")["wan"], 200.0)
        self.assertEqual(_amount_text("柬埔寨新订单1,500万"), "1500万")

    def test_amount_text_is_not_scientific(self):
        from app.duzhan_ledger import num_text

        self.assertEqual(num_text(2000000), "2000000")
        self.assertEqual(num_text(1234.5), "1234.5")
        self.assertEqual(num_text(45.0), "45")


class TolerantNumericTests(unittest.TestCase):
    """审查修复：外部卡片/环境变量给脏值时不能崩，也不能静默变 0。"""

    def test_as_int_accepts_percent_and_rejects_junk(self):
        from app.duzhan_ledger import as_float, as_int

        self.assertEqual(as_int("100%"), 100)
        self.assertEqual(as_int("已完成"), 0)
        self.assertEqual(as_int(None, 7), 7)
        self.assertEqual(as_int(True), 0)
        self.assertEqual(as_float("1.5"), 1.5)
        self.assertEqual(as_float("abc", 2.5), 2.5)

    def test_daily_report_with_dirty_progress(self):
        from app.duzhan_ledger import parse_daily_reports

        messages = [
            {
                "created_at": "2026-09-18T10:00:00Z",
                "metadata": {
                    "kind": "daily_report_submission",
                    "work_date": "2026-09-18",
                    "submitter_name": "于冰",
                    "today": [
                        {"progress": "100%", "spent_hours": "1.5"},
                        {"progress": "已完成", "spent_hours": 2},
                    ],
                },
            }
        ]
        reports = parse_daily_reports(messages, "2026-09-18")
        self.assertEqual(reports["于冰"]["done_count"], 1)
        self.assertEqual(reports["于冰"]["spent_hours"], 3.5)


class ConfigToleranceTests(unittest.TestCase):
    """审查修复：PDCA_* 空串/非数字不能让进程起不来；true/yes/on 不能被当成关闭。"""

    def test_bad_values_fall_back(self):
        import os

        from app.config import Settings

        with mock.patch.dict(
            os.environ,
            {"PDCA_WORKERS": "", "PDCA_WORKBENCH_PORT": "abc", "PDCA_SECURE_COOKIES": "yes"},
            clear=False,
        ):
            settings = Settings()
        self.assertEqual(settings.workers, 2)
        self.assertEqual(settings.port, 8767)
        self.assertTrue(settings.secure_cookies, "yes 必须当开启")

    def test_helpers_accept_common_truthy_strings(self):
        import os

        from app.config import _env_flag, _env_int

        with mock.patch.dict(os.environ, {"PDCA_TEST_FLAG": "on", "PDCA_TEST_INT": ""}, clear=False):
            self.assertTrue(_env_flag("PDCA_TEST_FLAG", "0"))
            self.assertEqual(_env_int("PDCA_TEST_INT", "9"), 9)


class MtoParsingRegressionTests(unittest.TestCase):
    """审查修复：型号被腰斩 / 两段 JSON / 没配密钥时不能拿图片数冒充达标数。"""

    def test_model_names_keep_single_char_suffix(self):
        from app.mto_ocr import _clean_model, parse_quote_text

        self.assertEqual(_clean_model("Vertu Constellation Quest"), "Vertu Constellation Quest")
        self.assertEqual(_clean_model("Vertu Metavertu 2"), "Vertu Metavertu 2")
        row = parse_quote_text("机型 Vertu Metavertu 2 报价 USD 45000")
        self.assertEqual(row["model"], "Vertu Metavertu 2")

    def test_last_json_block_wins(self):
        from app.mto_ocr import parse_quote_text

        text = '先给示例：{"model": "VERTU"}\n最终：{"model": "Vertu Aster P", "total_usd": 45000}'
        row = parse_quote_text(text)
        self.assertEqual(row["model"], "Vertu Aster P")
        self.assertEqual(row["usd"], 45000.0)

    def test_no_key_means_pending_not_image_count(self):
        from app import mto_ocr

        messages = [
            {
                "sender_user_id": 7,
                "message_type": "image",
                "attachments": [{"attachment_type": "image", "url": f"/f/{index}.jpg"}],
            }
            for index in range(3)
        ]
        settings = mock.Mock(qwen_api_key="", mto_ocr_max_images=8)
        with mock.patch.object(mto_ocr, "get_settings", lambda: settings):
            count, names, quotes = mto_ocr.review_mto_images(messages, 7)
        self.assertIsNone(count, "没读图就不能给「达标款数」")
        self.assertEqual(len(names), 3)
        self.assertEqual(quotes, [])


class DailyReportSourceHonestyTests(unittest.TestCase):
    """审查修复：日报群取数失败必须写「待确认」，不能替人下「未见日报」的结论。"""

    def test_source_failure_renders_pending_and_no_gap(self):
        from app.duzhan import _daily_report_text
        from app.duzhan_ledger import PersonRow, score_row

        row = PersonRow(group="于冰业绩达标群", display="于冰", daily_report_ok=False)
        scored = score_row(row)
        self.assertNotIn("未报今日任务", scored.gaps)
        self.assertIn("待确认", _daily_report_text({"daily_report": {}, "daily_report_ok": False}, "zh"))
        self.assertIn("未见今日正式日报", _daily_report_text({"daily_report": {}}, "zh"))


class PusherLoggingTests(unittest.TestCase):
    """审查修复：vps_im_push 少 import logger，任何推送失败都会抛 NameError。"""

    def test_failure_path_returns_false_instead_of_raising(self):
        from app import vps_im_push

        class Resp:
            status_code = 500
            text = "boom"

        self.assertTrue(hasattr(vps_im_push, "logger"))
        with mock.patch.object(vps_im_push, "_file_channel", lambda path: "chan-1"), mock.patch.object(
            vps_im_push.httpx, "post", lambda *a, **k: Resp()
        ), mock.patch.object(
            vps_im_push, "get_settings", lambda: mock.Mock(vps_bot_app_id="id", vps_bot_app_secret="sec")
        ):
            self.assertFalse(vps_im_push.push_vps_message("hello"))


class RetentionAndReminderTests(unittest.TestCase):
    """老板 2026-09-20 拍板：证据 HTML 不压缩、发完继续留 2 周；每周提醒备份一次；
    MTO 残图改成每小时清理 + 6 小时阈值。"""

    def test_prune_keeps_two_weeks(self):
        import os
        import tempfile
        from pathlib import Path

        from app.scheduler.jobs import _prune_evidence_reports

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(20):
                name = f"督战证据_2026-09-{index + 1:02d}"
                html = root / f"{name}.html"
                html.write_text("x", encoding="utf-8")
                (root / f"{name}.json").write_text("{}", encoding="utf-8")
                os.utime(html, (1000 + index, 1000 + index))
            _prune_evidence_reports(root, keep=14)
            left = sorted(item.name for item in root.glob("*.html"))
            self.assertEqual(len(left), 14, left)
            self.assertNotIn("督战证据_2026-09-01.html", left)
            self.assertEqual(len(list(root.glob("*.json"))), 14, "同名 json 要一起删")

    def test_default_keep_days_is_two_weeks(self):
        from app.config import get_settings

        self.assertEqual(get_settings().evidence_report_keep_days, 14)

    def test_jobs_are_registered_as_configured(self):
        from app.scheduler import jobs

        scheduler = jobs.start_scheduler()
        self.assertIsNotNone(scheduler)
        ids = {item.id for item in scheduler.get_jobs()}
        self.assertIn("backup_reminder", ids)
        self.assertIn("mto_temp_cleanup", ids)
        cleanup = scheduler.get_job("mto_temp_cleanup")
        self.assertEqual(str(cleanup.trigger), "cron[minute='15']", "MTO 残图改成每小时清理")
        reminder = scheduler.get_job("backup_reminder")
        self.assertIn("day_of_week='mon'", str(reminder.trigger))


if __name__ == "__main__":
    unittest.main()