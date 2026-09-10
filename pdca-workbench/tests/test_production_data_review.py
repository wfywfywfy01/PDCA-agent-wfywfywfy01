"""Production data regressions: cumulative snapshots, missing facts and source dates."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.dashboard import router as dashboard, service
from app.logistics import service as logistics
from app.models.dealer_sales import DealerSales
from app.models.dealer_store import DealerStore
from app.models.logistics import LogisticsShipment
from app.models.meeting import MeetingRecord
from app.models.walkin_daily_report import WalkinDailyReport
from app.vertu import sales
from app.walkin import router as walkin


class ProductionDataReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'data.sqlite'}")
        SQLModel.metadata.create_all(self.engine)
        self.admin = User(username="review-admin", display_name="Review", role="admin", hashed_password="unused")
        with Session(self.engine) as session:
            session.add(DealerStore(store_id="real-store", name="Real Store"))
            session.add_all([
                DealerSales(check_date="2026-08-18", dealer_name="Real Store", sell_in_wan=8),
                DealerSales(check_date="2026-08-19", dealer_name="Real Store", sell_in_wan=12),
                DealerSales(check_date="2026-08-20", dealer_name="Real Store", sell_in_wan=15),
            ])
            session.commit()

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_month_kpi_uses_one_snapshot_at_or_before_requested_date(self):
        with Session(self.engine) as session:
            result = service.merge_db_sales({}, "2026-08-19", session, self.admin, period="month")
        self.assertEqual(result["sellInWan"], 12)
        self.assertNotIn("sellOutWan", result)  # Sell-in rows are not terminal revenue evidence.
        self.assertTrue(result["dataAsOf"].endswith("+00:00"))

    def test_non_month_kpi_never_substitutes_monthly_snapshot(self):
        with Session(self.engine) as session:
            for period in ("day", "week", "quarter"):
                result = service.merge_db_sales({}, "2026-08-19", session, self.admin, period=period)
                self.assertIsNone(result.get("sellInWan"))

    def test_overview_five_kit_obeys_selected_period(self):
        with Session(self.engine) as session:
            session.add_all([
                WalkinDailyReport(report_date="2026-08-18", dealer_id="real-store", dealer_name="Real Store", deal_amount_yuan=100),
                WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", deal_amount_yuan=25),
            ])
            session.commit()
            result = service.merge_db_sales({}, "2026-08-19", session, self.admin, period="day")
        self.assertEqual(result["sellOutUsd"], 25)

    def test_no_snapshot_is_missing_in_trend_not_zero(self):
        with Session(self.engine) as session:
            result = service.db_sellin_summary("2026-08", session)
        self.assertIsNone(result["trend"][0]["wan"])

    def test_latest_snapshot_total_includes_returns(self):
        with Session(self.engine) as session:
            session.add(DealerSales(check_date="2026-08-20", dealer_name="Returned Store", sell_in_wan=-3, units=-1))
            session.commit()
            result = service.db_sellin_summary("2026-08", session)
        self.assertEqual(result["total_wan"], 12)

    def test_missing_upstream_headline_fails_instead_of_publishing_live_zero(self):
        sales._SELL_IN_CACHE.clear()
        sales._SELL_IN_LOCKS.clear()
        with patch.object(sales, "_headline", return_value={}):
            with self.assertRaises(RuntimeError):
                asyncio.run(sales.fetch_sell_in("2026-08-19", "day"))

    def test_zero_upstream_headline_is_valid(self):
        sales._SELL_IN_CACHE.clear()
        sales._SELL_IN_LOCKS.clear()
        with patch.object(sales, "_headline", return_value={"period": {"销额": 0, "销量": 0}}):
            result = asyncio.run(sales.fetch_sell_in("2026-08-19", "day"))
        self.assertEqual(result["amount"], 0)
        self.assertEqual(result["state"], "live")

    def test_five_kit_real_zero_replaces_legacy_nonzero(self):
        with Session(self.engine) as session:
            session.add(WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store"))
            session.commit()
            result = walkin._merge_five_kit_into_payload({"stores": [{"id": "real-store", "totalVisitGroups": 99, "touchCount": 55, "dealGroups": 9, "reportedSellOutUsd": 999}]}, "2026-08", session)
        row = result["stores"][0]
        self.assertEqual(row["totalVisitGroups"], 0)
        self.assertEqual(row["touchCount"], 0)
        self.assertEqual(row["dealGroups"], 0)
        self.assertEqual(row["reportedSellOutUsd"], 0)

    def test_invalid_range_is_rejected_instead_of_loading_all_history(self):
        with Session(self.engine) as session:
            for start, end in (("2026-08-01", ""), ("2026-08-19", "2026-08-01"), ("2026-02-30", "2026-03-01")):
                with self.assertRaises(HTTPException) as exc:
                    asyncio.run(walkin.walkin_metrics_summary(self.admin, session, month="", start=start, end=end))
                self.assertEqual(exc.exception.status_code, 422)

    def test_logistics_preserves_original_batch_date(self):
        with Session(self.engine) as session:
            session.add(LogisticsShipment(record_date="2026-08-12", tracking_number="REAL123", customer="Real Customer"))
            session.commit()
        with patch("app.database.get_engine", return_value=self.engine):
            rows = logistics._load_db_rows("all")
        self.assertEqual(rows[0]["record_date"], "2026-08-12")

    def test_not_delivered_is_not_classified_as_delivered(self):
        for status in ("Not delivered", "Undelivered", "Delivery attempted, not delivered"):
            self.assertFalse(logistics._status_is_delivered(status), status)
        self.assertTrue(logistics._status_is_delivered("Delivered to recipient"))

    def test_logistics_db_failure_is_not_an_empty_success(self):
        settings = SimpleNamespace(mvp_root=Path(self.temp.name), config_dir=Path(self.temp.name), include_demo_data=False)
        with patch.object(logistics, "get_settings", return_value=settings), patch.object(logistics, "_load_db_rows", return_value=None), patch.object(logistics, "load_auto_status_map", return_value={}):
            rows, state = logistics.load_shipments("all", return_state=True)
        self.assertEqual(rows, [])
        self.assertEqual(state, "missing")

    def test_logistics_failed_db_write_does_not_export_or_report_success(self):
        with patch("app.models.writes.get_engine", side_effect=RuntimeError("database offline")), patch("app.legacy.bridge.append_logistics") as append:
            with self.assertRaisesRegex(RuntimeError, "物流保存失败"):
                logistics.create_shipment("2026-08-19", {"tracking_number": "REAL123"})
        append.assert_not_called()

    def test_logistics_csv_failure_preserves_successful_db_write(self):
        with patch("app.models.writes.get_engine", return_value=self.engine), patch("app.legacy.bridge.append_logistics", side_effect=OSError("read only export")):
            result = logistics.create_shipment("2026-08-19", {"tracking_number": "REAL123"})
        self.assertEqual(result, "REAL123")
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(LogisticsShipment)).all()), 1)

    def test_logistics_workbench_reads_db_even_without_csv_directory(self):
        with patch.object(logistics, "load_shipments", return_value=([{"tracking_number": "REAL123", "judgement": "待核查", "is_delivered": False}], "available")), Session(self.engine) as session:
            result = asyncio.run(dashboard.workbench_today("2026-08-19", self.admin, session))
        fact = result["facts"]["logistics_attention"]
        self.assertEqual(fact["value"], 1)
        self.assertEqual(fact["source"], "logistics_db")

    def test_target_validation_rejects_negative_infinite_and_invalid_rate(self):
        from app.admin.router import TargetUpsertBody
        for fields in ({"sell_out_target_yuan": -1}, {"visit_target": -1}, {"deal_target": -1}, {"add_rate_target": 1.1}, {"sell_out_target_yuan": float("inf")}, {"add_rate_target": float("nan")}):
            with self.assertRaises(ValidationError):
                TargetUpsertBody(month="2026-08", **fields)

    def test_target_rejects_nonexistent_month(self):
        from app.admin.router import TargetUpsertBody, upsert_target
        with Session(self.engine) as session, self.assertRaises(HTTPException) as exc:
            asyncio.run(upsert_target(TargetUpsertBody(month="2026-99"), self.admin, session))
        self.assertEqual(exc.exception.status_code, 422)

    def test_review_only_revenue_is_missing_not_zero(self):
        with Session(self.engine) as session:
            session.add(WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", deal_amount_yuan=2000000))
            session.commit()
            result = asyncio.run(dashboard.sell_out("2026-08-19", "day", self.admin, session))
            summary = asyncio.run(walkin.walkin_metrics_summary(self.admin, session, month="2026-08", start="", end=""))
            cockpit = walkin._merge_five_kit_into_payload({}, "2026-08", session)
        self.assertIsNone(result["amount"])
        self.assertEqual(result["state"], "missing")
        self.assertEqual(result["review_count"], 1)
        self.assertIsNone(summary["funnel"]["deal_amount_usd"])
        self.assertIsNone(summary["by_dealer"][0]["deal_amount_usd"])
        self.assertIsNone(cockpit["stores"][0]["reportedSellOutUsd"])

    def test_empty_walkin_summary_keeps_complete_response_schema(self):
        with Session(self.engine) as session:
            summary = asyncio.run(walkin.walkin_metrics_summary(
                self.admin, session, month="2026-09", start="", end="",
            ))
        self.assertEqual(summary["five_kit"]["pct"], {
            "walkin": 0, "cross": 0, "online": 0, "recruit": 0, "existing": 0,
        })

    def test_five_kit_resubmit_preserves_versions_and_freshness(self):
        with Session(self.engine) as session:
            session.add(WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", created_at=datetime(2026, 8, 19)))
            session.commit()
            with patch.object(walkin, "log_action"), patch.object(walkin.bridge, "today_text", return_value="2026-08-20"):
                asyncio.run(walkin.submit_walkin_metrics(walkin.WalkinMetricsSubmit(report_date="2026-08-19", dealer_id="real-store", dealer_name="Ignored Name", deal_amount_yuan=42), self.admin, session))
            rows = session.exec(select(WalkinDailyReport)).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].dealer_name, "Real Store")
        self.assertEqual(rows[0].deal_amount_yuan, 0)
        self.assertEqual(rows[1].deal_amount_yuan, 42)
        self.assertGreater(rows[1].created_at, datetime(2026, 8, 19))

    def test_single_day_meetings_do_not_include_following_days(self):
        from app.meeting.router import _db_meetings
        with Session(self.engine) as session:
            session.add_all([MeetingRecord(meeting_date="2026-08-18", external_id="M18"), MeetingRecord(meeting_date="2026-08-19", external_id="M19")])
            session.commit()
            result = _db_meetings("2026-08-18", "", "", session)
        self.assertEqual(len(result["meetings"]), 1)
        self.assertEqual(result["meetings"][0]["meeting_date"], "2026-08-18")

    def test_bridge_meeting_date_is_not_invented_for_multiday_range(self):
        from app.meeting import router as meeting
        with Session(self.engine) as session, patch.object(meeting.bridge, "api_meeting_center_meetings", return_value={"meetings": [{"id": "M1"}, {"id": "M2", "started_at": "2026-08-19T10:00:00+08:00"}]}):
            result = meeting._load_meetings("2026-08-18", "2026-08-20", "", "", self.admin, session)
        self.assertIsNone(result["meetings"][0]["meeting_date"])
        self.assertEqual(result["meetings"][1]["meeting_date"], "2026-08-19")

    def test_historical_duplicate_reports_use_latest_row_and_preserve_new_version(self):
        from app.export.router import export_walkin_metrics
        captured = []
        with Session(self.engine) as session:
            # Equal timestamps exercise the stable primary-key tie breaker.
            session.add_all([
                WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", created_at=datetime(2026, 8, 19), walkin_visits=100, deal_amount_yuan=1000),
                WalkinDailyReport(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", created_at=datetime(2026, 8, 19), walkin_visits=4, deal_amount_yuan=40),
            ])
            session.commit()
            summary = asyncio.run(walkin.walkin_metrics_summary(self.admin, session, month="2026-08", start="", end=""))
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["five_kit"]["total"], 4)
            self.assertEqual(summary["funnel"]["deal_amount_usd"], 40)
            listing = asyncio.run(walkin.list_walkin_metrics(self.admin, session, month="2026-08", dealer_id=""))
            self.assertEqual(listing["count"], 1)
            merged = service.merge_db_sales({}, "2026-08-19", session, self.admin, period="day")
            self.assertEqual(merged["sellOutUsd"], 40)
            sellout = asyncio.run(dashboard.sell_out("2026-08-19", "day", self.admin, session))
            self.assertEqual(sellout["amount"], 40)
            with patch("app.export.router._wb_response", side_effect=lambda wb, name: captured.append(wb)):
                asyncio.run(export_walkin_metrics(self.admin, session, month="2026-08", dealer_id=""))
            self.assertEqual(captured[0].active.max_row, 2)
            self.assertEqual(captured[0].active.cell(2, 14).value, 40)
            with patch.object(walkin, "log_action"), patch.object(walkin.bridge, "today_text", return_value="2026-08-20"):
                asyncio.run(walkin.submit_walkin_metrics(walkin.WalkinMetricsSubmit(report_date="2026-08-19", dealer_id="real-store", dealer_name="Real Store", deal_amount_yuan=50), self.admin, session))
            rows = session.exec(select(WalkinDailyReport).order_by(WalkinDailyReport.id)).all()
            self.assertEqual(len(rows), 3)  # Every submitted version is preserved.
            self.assertEqual(rows[0].deal_amount_yuan, 1000)
            self.assertEqual(rows[1].deal_amount_yuan, 40)
            self.assertEqual(rows[2].deal_amount_yuan, 50)

    def test_db_only_task_create_fails_without_false_success_audit(self):
        with Session(self.engine) as session, patch("app.models.writes.get_engine", side_effect=RuntimeError("database offline")), patch("app.audit.log_action") as audit:
            with self.assertRaises(HTTPException) as exc:
                asyncio.run(dashboard.task_center_create(dashboard.TaskCreateBody(task_date="2026-08-19", title="Real Task"), self.admin, session))
        self.assertEqual(exc.exception.status_code, 503)
        audit.assert_not_called()

    def test_csv_mirror_task_helper_still_does_not_raise(self):
        from app.models import writes
        with patch.object(writes, "get_engine", side_effect=RuntimeError("database offline")):
            self.assertFalse(writes.insert_pdca_task("2026-08-19", "Already saved in CSV"))

    def test_chinese_test_labels_tight_to_qa_are_excluded(self):
        from app.models.dealer_store import is_demo_store
        self.assertTrue(is_demo_store("real-id", "QA测试门店（可删除）"))
        self.assertTrue(is_demo_store("real-id", "qa演示门店"))
        self.assertFalse(is_demo_store("real-id", "Democratic Electronics"))
        self.assertFalse(is_demo_store("real-id", "Qatar Luxury Store"))

    def test_order_batch_rejects_missing_redacted_and_nonfinite_amounts(self):
        for value in (None, "", "***", float("nan"), float("inf")):
            payload = {"columns": ["客户名称", "金额", "数量"], "rows": [["Real Store", value, 703]]}
            with patch.object(sales, "run_vertu_sync_json", return_value=payload), self.assertRaises(RuntimeError):
                sales.fetch_dealer_sales_orders_sync("2026-08-01", "2026-08-31")
        with patch.object(sales, "run_vertu_sync_json", return_value={"rows": [{"客户名称": "Real Store", "数量": 703}]}), self.assertRaises(RuntimeError):
            sales.fetch_dealer_sales_orders_sync("2026-08-01", "2026-08-31")

    def test_order_batch_rejects_missing_customer_but_accepts_named_zero(self):
        payload = {"columns": ["客户名称", "金额", "数量"], "rows": [["Real Store", 0, 1], [" ", 100, 2]]}
        with patch.object(sales, "run_vertu_sync_json", return_value=payload), self.assertRaisesRegex(RuntimeError, "缺少客户标识"):
            sales.fetch_dealer_sales_orders_sync("2026-08-01", "2026-08-31")
        payload["rows"] = [["Real Store", 0, 1]]
        with patch.object(sales, "run_vertu_sync_json", return_value=payload):
            result = sales.fetch_dealer_sales_orders_sync("2026-08-01", "2026-08-31")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["dealers"][0]["qty"], 1)
        self.assertEqual(result["dealers"][0]["dealer_name"], "Real Store")

    def test_suspect_legacy_snapshot_keeps_quantity_but_not_false_zero_amount(self):
        from app.export.router import export_dealer_sales
        exported = []
        with Session(self.engine) as session:
            session.add(DealerSales(check_date="2026-08-31", dealer_name="Real Store", sell_in_wan=0, units=703, source_file="vertu-cli:sales-orders"))
            session.commit()
            summary = service.db_sellin_summary("2026-08", session)
            overview = service.merge_db_sales({}, "2026-08-31", session, self.admin, period="month")
            raw = session.exec(select(DealerSales).where(DealerSales.check_date == "2026-08-31")).one()
            with patch("app.export.router._wb_response", side_effect=lambda wb, name: exported.append(wb)):
                asyncio.run(export_dealer_sales(self.admin, session, month="2026-08"))
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["snapshot_date"], "2026-08-31")
        self.assertEqual(summary["amount_state"], "suspect")
        self.assertIsNone(summary["total_wan"])
        self.assertIsNone(summary["dealers"][0]["wan"])
        self.assertIsNone(summary["dealers"][0]["rank"])
        self.assertEqual(summary["dealers"][0]["quantity"], 703)
        self.assertIsNone(summary["trend"][-1]["wan"])
        self.assertIsNone(overview["sellInWan"])
        self.assertEqual(raw.sell_in_wan, 0)
        exported_row = next(row for row in exported[0].active.iter_rows(values_only=True) if row[0] == "2026-08-31")
        self.assertIsNone(exported_row[4])
        self.assertIn("待复核", exported_row[-1])

    def test_verified_zero_amount_remains_real_zero_with_units(self):
        from app.models.dealer_sales import snapshot_amount_state
        self.assertEqual(snapshot_amount_state([DealerSales(check_date="2026-08-31", dealer_name="Real Store", sell_in_wan=0, units=1, source_file="vertu-cli:sales-orders:validated")]), "available")

    def _seed_vps_snapshot(self, *, source="vertu-cli:sales-orders"):
        with Session(self.engine) as session:
            session.add_all([
                DealerSales(check_date="2026-08-31", dealer_name="Real Store", sell_in_wan=42, units=7, source_file=source),
                DealerSales(check_date="2026-08-31", dealer_name="Removed Store", sell_in_wan=12, units=2, source_file=source),
            ])
            session.commit()

    def test_sync_bad_amount_preserves_existing_snapshot(self):
        from app.models import sync
        self._seed_vps_snapshot()
        with patch.object(sync, "get_engine", return_value=self.engine), patch.object(sales, "fetch_dealer_sales_orders_sync", return_value={"dealers": [{"dealer_name": "Real Store", "qty": 703}]}):
            with self.assertRaises(RuntimeError):
                sync.sync_dealer_sales_from_vps("2026-08-31")
        with Session(self.engine) as session:
            self.assertEqual(sum(row.sell_in_wan for row in session.exec(select(DealerSales).where(DealerSales.check_date == "2026-08-31")).all()), 54)

    def test_sync_atomically_replaces_only_requested_vps_date(self):
        from app.models import sync
        self._seed_vps_snapshot()
        with patch.object(sync, "get_engine", return_value=self.engine), patch.object(sales, "fetch_dealer_sales_orders_sync", return_value={"dealers": [{"dealer_name": "Real Store", "qty": 703, "sell_out_yuan": 7880563.34}]}):
            self.assertEqual(sync.sync_dealer_sales_from_vps("2026-08-31"), 1)
        with Session(self.engine) as session:
            current = session.exec(select(DealerSales).where(DealerSales.check_date == "2026-08-31")).all()
            previous = session.exec(select(DealerSales).where(DealerSales.check_date != "2026-08-31")).all()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].dealer_name, "Real Store")
        self.assertEqual(current[0].source_file, "vertu-cli:sales-orders:validated")
        self.assertEqual(len(previous), 3)

    def test_sync_commit_failure_rolls_back_deleted_snapshot(self):
        from app.models import sync
        self._seed_vps_snapshot()
        with patch.object(sync, "get_engine", return_value=self.engine), patch.object(sales, "fetch_dealer_sales_orders_sync", return_value={"dealers": [{"dealer_name": "Real Store", "qty": 703, "sell_out_yuan": 10000}]}), patch.object(Session, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                sync.sync_dealer_sales_from_vps("2026-08-31")
        with Session(self.engine) as session:
            old = session.exec(select(DealerSales).where(DealerSales.check_date == "2026-08-31")).all()
        self.assertEqual(len(old), 2)
        self.assertEqual(sum(row.sell_in_wan for row in old), 54)

    def test_sync_never_deletes_manual_import_rows(self):
        from app.models import sync
        self._seed_vps_snapshot(source="manual-import.json")
        with patch.object(sync, "get_engine", return_value=self.engine), patch.object(sales, "fetch_dealer_sales_orders_sync", return_value={"dealers": [{"dealer_name": "Real Store", "qty": 703, "sell_out_yuan": 10000}]}):
            with self.assertRaisesRegex(RuntimeError, "非 VPS 来源"):
                sync.sync_dealer_sales_from_vps("2026-08-31")
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(DealerSales).where(DealerSales.source_file == "manual-import.json")).all()), 2)

    def test_sync_api_reports_failure_instead_of_zero_row_success(self):
        from app.admin.router import trigger_vps_sellout_sync
        with patch("app.admin.router.sync_dealer_sales_from_vps", side_effect=RuntimeError("invalid upstream amount")), self.assertRaises(HTTPException) as exc:
            asyncio.run(trigger_vps_sellout_sync("2026-08-31", self.admin))
        self.assertEqual(exc.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
