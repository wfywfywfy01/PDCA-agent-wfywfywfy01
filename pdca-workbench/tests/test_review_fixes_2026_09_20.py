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
            self.assertEqual(Settings().mto_ocr_workers, 2)

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


if __name__ == "__main__":
    unittest.main()