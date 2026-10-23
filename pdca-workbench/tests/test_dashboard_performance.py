from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.dashboard import service
from app.dashboard.router import _sales_payload
from app.vertu import sales


class DashboardPerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        sales._SELL_IN_CACHE.clear()
        sales._SELL_IN_LOCKS.clear()

    async def test_default_sell_in_includes_all_five_departments_and_keeps_real_zero(self) -> None:
        amounts = {
            "经销商一部": 10000,
            "经销商二部": 20000,
            "经销商三部": 30000,
            "经销商四部": 40000,
            "经销商五部": 0,
        }

        async def fake_run(args, timeout):
            department = args[args.index("--dept-l2") + 1]
            return {"period": {"销额": amounts[department], "销量": 0 if department == "经销商五部" else 1}}

        with (
            patch.dict(os.environ, {"PDCA_VERTU_DEPT_L1": "海外渠道"}),
            patch.object(sales, "run_vertu_json", side_effect=fake_run) as run,
        ):
            os.environ.pop("PDCA_VERTU_SELLIN_DEPARTMENTS", None)
            result = await sales.fetch_sell_in("2026-10-23", "month")
            cached = await sales.fetch_sell_in("2026-10-23", "month")

        departments = [call.args[0][call.args[0].index("--dept-l2") + 1] for call in run.call_args_list]
        self.assertEqual(departments, list(amounts))
        self.assertEqual(result["amount"], 100000)
        self.assertEqual(result["wan"], 10)
        self.assertEqual(result["quantity"], 4)
        self.assertEqual(result["state"], "live")
        self.assertEqual((result["start_date"], result["end_date"]), ("2026-10-01", "2026-10-23"))
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["as_of"], result["as_of"])

    async def test_all_sales_aggregates_share_default_and_explicit_department_scope(self) -> None:
        cases = [
            (None, ["经销商一部", "经销商二部", "经销商三部", "经销商四部", "经销商五部"], 50000),
            (" 经销商四部,经销商五部,经销商四部,, ", ["经销商四部", "经销商五部"], 20000),
        ]

        async def fake_run(args, timeout):
            if args[1] == "+headline-kpi":
                return {"period": {"销额": 10000, "销量": 1}}
            if args[1] == "+target-achievement":
                return {"rows": [{"target_amount": 10000}]}
            return {"rows": [{"name": "Alice", "amount": 10000, "qty": 1, "orders": 1}]}

        for configured, expected_departments, expected_amount in cases:
            with (
                self.subTest(configured=configured),
                patch.dict(os.environ, {"PDCA_VERTU_DEPT_L1": "海外渠道"}),
                patch.object(sales, "_date", wraps=date) as current_date,
                patch.object(sales, "run_vertu_json", side_effect=fake_run) as run,
            ):
                current_date.today.return_value = date(2026, 10, 23)
                if configured is None:
                    os.environ.pop("PDCA_VERTU_SELLIN_DEPARTMENTS", None)
                else:
                    os.environ["PDCA_VERTU_SELLIN_DEPARTMENTS"] = configured
                sell_in = await sales.fetch_sell_in("2026-10-23", "month")
                target = await asyncio.to_thread(sales.fetch_dept_monthly_target, "2026-10-01", "2026-10-31")
                breakdown = await sales.fetch_salesperson_breakdown("2026-08")

            self.assertEqual(sell_in["amount"], expected_amount)
            self.assertEqual(target, expected_amount)
            self.assertEqual(breakdown["total_wan"], expected_amount / 10000)
            for command, start, end in [
                ("+headline-kpi", "2026-10-01", "2026-10-23"),
                ("+target-achievement", "2026-10-01", "2026-10-31"),
                ("+dept-breakdown", "2026-08-01", "2026-08-31"),
            ]:
                args_list = [call.args[0] for call in run.call_args_list if call.args[0][1] == command]
                self.assertEqual([args[args.index("--dept-l2") + 1] for args in args_list], expected_departments)
                for args in args_list:
                    self.assertEqual(args[args.index("--dept-l1") + 1], "海外渠道")
                    self.assertEqual(args[args.index("--start-date") + 1], start)
                    self.assertEqual(args[args.index("--end-date") + 1], end)

    async def test_zero_for_all_five_departments_remains_live(self) -> None:
        with (
            patch.dict(os.environ, {}),
            patch.object(sales, "run_vertu_json", return_value={"period": {"销额": 0, "销量": 0}}) as run,
        ):
            os.environ.pop("PDCA_VERTU_SELLIN_DEPARTMENTS", None)
            result = await sales.fetch_sell_in("2026-10-23", "month")

        self.assertEqual(run.call_count, 5)
        self.assertEqual((result["amount"], result["wan"], result["quantity"]), (0, 0, 0))
        self.assertEqual(result["state"], "live")

    async def test_explicit_empty_departments_preserves_existing_behavior(self) -> None:
        with (
            patch.dict(os.environ, {"PDCA_VERTU_SELLIN_DEPARTMENTS": " , "}),
            patch.object(sales, "run_vertu_json", return_value={"rows": []}) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "未配置经销商部门"):
                await sales.fetch_sell_in("2026-10-23", "month")
            run.assert_not_called()
            self.assertEqual(await asyncio.to_thread(sales.fetch_dept_monthly_target, "2026-10-01", "2026-10-31"), 0)
            run.assert_not_called()
            result = await sales.fetch_salesperson_breakdown("2026-08")

        self.assertEqual(run.call_count, 1)
        self.assertNotIn("--dept-l2", run.call_args.args[0])
        self.assertFalse(result["has_data"])

    async def test_sell_in_cache_separates_date_period_and_department_configuration(self) -> None:
        cases = [
            ("2026-10-22", "month", "2026-10-01", "2026-10-22"),
            ("2026-10-23", "day", "2026-10-23", "2026-10-23"),
            ("2026-10-23", "week", "2026-10-19", "2026-10-23"),
            ("2026-10-23", "quarter", "2026-10-01", "2026-10-23"),
        ]
        with (
            patch.dict(os.environ, {"PDCA_VERTU_DEPT_L1": "海外渠道", "PDCA_SELL_IN_CACHE_SECONDS": "60"}),
            patch.object(sales, "run_vertu_json", return_value={"period": {"销额": 10000, "销量": 1}}) as run,
        ):
            os.environ.pop("PDCA_VERTU_SELLIN_DEPARTMENTS", None)
            await sales.fetch_sell_in("2026-10-23", "month")
            self.assertTrue((await sales.fetch_sell_in("2026-10-23", "month"))["cached"])
            self.assertEqual(run.call_count, 5)
            for date, period, start, end in cases:
                with self.subTest(date=date, period=period):
                    before = run.call_count
                    result = await sales.fetch_sell_in(date, period)
                    self.assertFalse(result["cached"])
                    self.assertEqual(run.call_count - before, 5)
                    self.assertEqual((result["start_date"], result["end_date"]), (start, end))
                    for call in run.call_args_list[before:]:
                        args = call.args[0]
                        self.assertEqual(args[args.index("--start-date") + 1], start)
                        self.assertEqual(args[args.index("--end-date") + 1], end)
            os.environ["PDCA_VERTU_SELLIN_DEPARTMENTS"] = "经销商四部"
            scoped = await sales.fetch_sell_in("2026-10-23", "month")
            self.assertFalse(scoped["cached"])
            self.assertEqual(scoped["amount"], 10000)
            os.environ["PDCA_VERTU_DEPT_L1"] = "明确配置的一级部门"
            self.assertFalse((await sales.fetch_sell_in("2026-10-23", "month"))["cached"])
            self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--dept-l1") + 1], "明确配置的一级部门")

    async def test_sell_in_departments_run_concurrently_and_cache_result(self) -> None:
        started: list[str] = []
        all_started = asyncio.Event()

        async def fake_headline(_start: str, _end: str, department: str = "") -> dict:
            started.append(department)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=0.5)
            return {"period": {"销额": 10000, "销量": 2}}

        env = {
            "PDCA_VERTU_SELLIN_DEPARTMENTS": "经销商一部,经销商二部,经销商三部",
            "PDCA_SELL_IN_CACHE_SECONDS": "60",
        }
        with patch.dict(os.environ, env), patch.object(sales, "_headline", side_effect=fake_headline):
            first = await sales.fetch_sell_in("2026-07-20", "month")
            second = await sales.fetch_sell_in("2026-07-20", "month")

        self.assertEqual(started, ["经销商一部", "经销商二部", "经销商三部"])
        self.assertEqual(first["amount"], 30000)
        self.assertEqual(first["quantity"], 6)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["as_of"], first["as_of"])
        self.assertIn("更新", first["note"])

    def test_workbench_overview_uses_authenticated_session_without_remote_lookup(self) -> None:
        session_user = {
            "username": "april",
            "display_name": "April",
            "role": "sales",
        }
        with patch.object(
            service.bridge,
            "api_dashboard_overview",
            side_effect=AssertionError("legacy remote overview must not run"),
        ):
            data = service.workbench_overview("2026-07-20", "month", session_user)

        self.assertEqual(data["managerName"], "April")
        self.assertEqual(data["managerRole"], "经销商销售 · 月视图 · 2026-07-20")
        self.assertIsNone(data["sellInWan"])
        self.assertEqual(data["dataState"]["sellIn"], "missing")

    def test_sales_payload_keeps_missing_distinct_from_real_zero(self) -> None:
        missing = _sales_payload(service.workbench_overview("2026-07-20"), "sellOut")
        zero = _sales_payload(
            {
                "sellOutWan": 0,
                "sellOutSub": "Odoo同步",
                "dataAsOf": "2026-07-20T09:00:00",
                "dataSource": {"sellOut": "dealer_sales_db"},
            },
            "sellOut",
        )

        self.assertIsNone(missing["amount"])
        self.assertIsNone(missing["wan"])
        self.assertEqual(zero["amount"], 0)
        self.assertEqual(zero["wan"], 0)
        self.assertEqual(zero["source"], "dealer_sales_db")

    def test_homepage_starts_sections_in_parallel(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (
            root
            / "data_platform"
            / "data_role_pdca_mvp"
            / "modules"
            / "home_dashboard"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("const overviewTask = loadSection('overview'", source)
        self.assertIn("const sellInTask = loadSection('sellIn'", source)
        self.assertIn("const customersTask = loadSection('customers'", source)
        self.assertIn("await Promise.allSettled([", source)

    async def test_salesperson_breakdown_normalizes_cli_rows(self) -> None:
        payload = {"rows": [{"name": "Alice", "amount": 123456, "qty": 3, "orders": 2}]}
        with (
            patch.dict(os.environ, {"PDCA_VERTU_SELLIN_DEPARTMENTS": ""}),
            patch.object(sales, "run_vertu_json", return_value=payload) as run,
        ):
            result = await sales.fetch_salesperson_breakdown("2026-08")
        self.assertEqual(result["rows"][0], {
            "rank": 1,
            "name": "Alice",
            "amount_wan": 12.35,
            "quantity": 3,
            "orders": 2,
        })
        self.assertEqual(result["total_wan"], 12.35)
        self.assertTrue(result["has_data"])
        self.assertIn("+dept-breakdown", run.call_args.args[0])
        self.assertIn("5000", run.call_args.args[0])

    async def test_salesperson_breakdown_matches_configured_sellin_departments(self) -> None:
        async def fake_run(args, timeout):
            department = args[args.index("--dept-l2") + 1]
            amount = 10000 if department == "经销商一部" else 20000
            return {"rows": [{"name": "Alice", "amount": amount, "qty": 1, "orders": 1}]}

        with (
            patch.dict(os.environ, {"PDCA_VERTU_SELLIN_DEPARTMENTS": "经销商一部,经销商二部"}),
            patch.object(sales, "run_vertu_json", side_effect=fake_run) as run,
        ):
            result = await sales.fetch_salesperson_breakdown("2026-08")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["rows"][0]["amount_wan"], 3.0)
        self.assertEqual(result["total_wan"], 3.0)

    async def test_salesperson_breakdown_skips_rows_without_name(self) -> None:
        payload = {"rows": [{"amount": 100, "qty": 1, "orders": 1}, {"name": "  ", "amount": 100}]}
        with (
            patch.dict(os.environ, {"PDCA_VERTU_SELLIN_DEPARTMENTS": ""}),
            patch.object(sales, "run_vertu_json", return_value=payload),
        ):
            result = await sales.fetch_salesperson_breakdown("2026-08")
        self.assertEqual(result["rows"], [])
        self.assertFalse(result["has_data"])


if __name__ == "__main__":
    unittest.main()
