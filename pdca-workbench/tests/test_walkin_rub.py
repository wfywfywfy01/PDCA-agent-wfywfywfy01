"""RUB is preserved end to end and contributes nothing to USD totals."""
import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.dashboard import router as dashboard, service
from app.export.router import export_walkin_metrics
from app.mcp_five_kit import _row
from app.models.dealer_store import DealerStore
from app.models.walkin_daily_report import WalkinDailyReport
from app.walkin import router as walkin


class WalkinRubTests(unittest.TestCase):
    def test_rub_round_trip_does_not_change_usd_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'rub.sqlite'}")
            SQLModel.metadata.create_all(engine)
            admin = User(username="test-admin", role="admin")
            try:
                with Session(engine) as session:
                    session.add(DealerStore(store_id="store", name="Store"))
                    session.commit()
                    with patch.object(walkin, "log_action"), patch.object(walkin.bridge, "today_text", return_value="2026-10-19"):
                        for day, amount, currency in (("2026-10-18", 125.5, "USD"), ("2026-10-19", 6_000_000.75, "RUB")):
                            body = walkin.WalkinMetricsSubmit(
                                report_date=day, dealer_id="store", dealer_name="Store",
                                walkin_visits=2, deal_count=1, deal_amount_yuan=amount,
                                revenue_currency=currency,
                            )
                            asyncio.run(walkin.submit_walkin_metrics(body, admin, session))
                    rub = session.exec(select(WalkinDailyReport).where(WalkinDailyReport.report_date == "2026-10-19")).one()
                    self.assertEqual(rub.deal_amount_rub, 6_000_000.75)
                    self.assertEqual(rub.deal_amount_yuan, 0)
                    items = asyncio.run(walkin.list_walkin_metrics(admin, session, month="2026-10", dealer_id=""))["items"]
                    rub_funnel = next(row["funnel"] for row in items if row["report_date"] == "2026-10-19")
                    self.assertEqual(rub_funnel["revenue_currency"], "RUB")
                    self.assertEqual(rub_funnel["revenue_amount"], 6_000_000.75)
                    self.assertIsNone(rub_funnel["deal_amount_usd"])
                    summary = asyncio.run(walkin.walkin_metrics_summary(admin, session, month="2026-10", start="", end=""))
                    self.assertEqual(summary["funnel"]["deal_amount_usd"], 125.5)
                    self.assertEqual(summary["five_kit"]["total"], 4)
                    self.assertEqual(service.merge_db_sales({}, "2026-10-19", session, admin, period="month")["sellOutUsd"], 125.5)
                    self.assertEqual(asyncio.run(dashboard.sell_out("2026-10-19", "month", admin, session))["amount"], 125.5)
                    self.assertIsNone(_row(rub)["deal_amount_usd"])
                    self.assertEqual(_row(rub)["revenue_amount"], 6_000_000.75)
                    captured = []
                    with patch("app.export.router._wb_response", side_effect=lambda wb, name: captured.append(wb)):
                        asyncio.run(export_walkin_metrics(admin, session, month="2026-10", dealer_id=""))
                    sheet = captured[0].active
                    self.assertEqual(sheet.cell(2, 14).value, 125.5)
                    self.assertIsNone(sheet.cell(3, 14).value)
                    self.assertEqual(sheet.cell(3, 18).value, "RUB")
                    self.assertEqual(sheet.cell(3, 19).value, 6_000_000.75)
            finally:
                engine.dispose()

    def test_currency_defaults_and_invalid_amounts(self):
        base = dict(report_date="2026-10-19", dealer_id="store", dealer_name="Store")
        self.assertEqual(walkin.WalkinMetricsSubmit(**base).revenue_currency, "USD")
        for values in ({"revenue_currency": "EUR"}, {"deal_amount_yuan": -1}, {"deal_amount_yuan": float("nan")}):
            with self.assertRaises(ValidationError):
                walkin.WalkinMetricsSubmit(**base, **values)

    def test_migration_preserves_existing_usd_and_is_idempotent(self):
        path = Path(__file__).resolve().parents[1] / "migrations/versions/022_walkin_rub.py"
        spec = importlib.util.spec_from_file_location("walkin_rub_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE walkin_daily_reports (id INTEGER PRIMARY KEY, deal_amount_yuan FLOAT NOT NULL)"))
                connection.execute(text("INSERT INTO walkin_daily_reports VALUES (1, 125.5)"))
                with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                    migration.upgrade()
                    migration.upgrade()
                self.assertIn("deal_amount_rub", {column["name"] for column in inspect(connection).get_columns("walkin_daily_reports")})
                self.assertEqual(connection.execute(text("SELECT deal_amount_yuan, deal_amount_rub FROM walkin_daily_reports")).one(), (125.5, None))
        finally:
            engine.dispose()
