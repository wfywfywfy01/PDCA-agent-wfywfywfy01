"""Opt-in integration checks against an explicitly supplied local test PostgreSQL.

Set PDCA_TEST_POSTGRES_URL to a disposable local cluster. Each test owns and
removes a random schema; SMTP is always mocked.
"""
import importlib.util
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

from app.growth import mailer
from app.growth.models import GrowthContent, GrowthDelivery, GrowthSend, GrowthUnsub


@unittest.skipUnless(os.environ.get("PDCA_TEST_POSTGRES_URL"), "local PostgreSQL test URL not set")
class GrowthPostgresTests(unittest.TestCase):
    def setUp(self):
        url = make_url(os.environ["PDCA_TEST_POSTGRES_URL"])
        if url.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("growth integration tests require a local disposable PostgreSQL")
        self.schema = "growth_test_" + uuid.uuid4().hex
        self.base_engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})
        self.addCleanup(self.base_engine.dispose)
        with self.base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addCleanup(self._drop_schema)
        self.engine = self.base_engine.execution_options(schema_translate_map={None: self.schema})
        for model in (GrowthContent, GrowthSend, GrowthUnsub, GrowthDelivery):
            model.__table__.create(self.engine)
        with Session(self.engine) as session:
            content = GrowthContent(round_no=1, kind="email", topic="test", variant="A",
                                    title="Subject", body="Hello")
            session.add(content)
            session.commit()
            self.cid = content.id
        self.environment = patch.dict(os.environ, {
            "PDCA_GROWTH_SMTP_HOST": "smtp.test", "PDCA_GROWTH_SMTP_PORT": "465",
            "PDCA_GROWTH_SMTP_USER": "sender@example.test", "PDCA_GROWTH_SMTP_PASSWORD": "offline",
            "PDCA_GROWTH_DAILY_CAP": "1",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _drop_schema(self):
        with self.base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def _concurrent_send(self, same_recipient):
        ready, release = threading.Event(), threading.Event()
        start = threading.Barrier(2)
        smtp = MagicMock()

        def accept(message):
            ready.set()
            self.assertTrue(release.wait(10))
            return {}

        smtp.send_message.side_effect = accept

        def worker(index):
            with Session(self.engine) as session:
                content = session.get(GrowthContent, self.cid)
                start.wait(10)
                address = "client@example.test" if same_recipient else f"client{index}@example.test"
                return mailer.send(session, content, [address])

        with patch.object(mailer.smtplib, "SMTP_SSL") as factory:
            factory.return_value.__enter__.return_value = smtp
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, index) for index in range(2)]
                try:
                    self.assertTrue(ready.wait(10))
                    finished, _ = wait(futures, timeout=5)
                    self.assertEqual(len(finished), 1, "duplicate/quota check must finish while SMTP waits")
                finally:
                    release.set()
                results = [future.result() for future in futures]
        self.assertEqual(smtp.send_message.call_count, 1)
        self.assertEqual(sum(len(result["sent"]) for result in results), 1)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(GrowthDelivery)).all()), 1)
            self.assertEqual(len(session.exec(select(GrowthSend)).all()), 1)

    def test_concurrent_same_recipient_uses_one_durable_claim(self):
        with patch.dict(os.environ, {"PDCA_GROWTH_DAILY_CAP": "25"}):
            self._concurrent_send(True)

    def test_concurrent_different_recipients_share_quota(self):
        self._concurrent_send(False)

    def test_quota_snapshot_does_not_lose_a_concurrently_finished_claim(self):
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            claim = GrowthDelivery(content_id=self.cid, to_addr="client@example.test",
                                   token="claim-token", message_id="<claim@example.test>", claimed_at=now)
            session.add(claim)
            session.commit()
            claim_id = claim.id

        def finish_claim():
            with Session(self.engine) as session:
                claim = session.get(GrowthDelivery, claim_id)
                session.add(GrowthSend(content_id=self.cid, to_addr=claim.to_addr, token=claim.token,
                                       message_id=claim.message_id, sent_at=now))
                mailer._finish_delivery(session, claim, "sent")

        with Session(self.engine) as session:
            original_exec = session.exec
            advanced = False

            def interleave(statement, *args, **kwargs):
                nonlocal advanced
                result = original_exec(statement, *args, **kwargs)
                if not advanced:
                    advanced = True
                    finish_claim()
                return result

            with patch.object(session, "exec", side_effect=interleave):
                self.assertEqual(mailer.quota_used_today(session, now), 1)
            self.assertTrue(advanced)
            self.assertEqual(mailer.quota_used_today(session, now), 1)

    def test_legacy_utc_history_counts_in_non_utc_database_session(self):
        with Session(self.engine) as session:
            session.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
            session.add(GrowthSend(content_id=self.cid, to_addr="legacy@example.test", token="legacy",
                                   sent_at=datetime(2026, 10, 22, 1)))
            session.commit()
            now = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
            with self.subTest(metric="quota"):
                self.assertEqual(mailer.quota_used_today(session, now), 1)
            with self.subTest(metric="confirmed"), patch.object(mailer, "datetime", wraps=datetime) as clock:
                clock.now.return_value = now
                self.assertEqual(mailer.sent_today(session), 1)

    def test_confirmed_send_preserves_utc_in_non_utc_database_session(self):
        with Session(self.engine) as session:
            session.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
            content = session.get(GrowthContent, self.cid)
            with patch.object(mailer.smtplib, "SMTP_SSL") as factory:
                factory.return_value.__enter__.return_value.send_message.return_value = {}
                result = mailer.send(session, content, ["client@example.test"])
            self.assertEqual(result["sent"], ["client@example.test"])
            sent = session.exec(select(GrowthSend)).one()
            claim = session.exec(select(GrowthDelivery)).one()
            sent_at = sent.sent_at
            if sent_at.tzinfo is None:  # Legacy GrowthSend columns contain naive UTC.
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            self.assertEqual(sent_at, claim.claimed_at)

    def test_migration_creates_claims_and_preserves_duplicate_send_history(self):
        with Session(self.engine) as session:
            session.add_all([GrowthSend(content_id=self.cid, to_addr="legacy@example.test", token=token)
                             for token in ("legacy-1", "legacy-2")])
            session.commit()
        GrowthDelivery.__table__.drop(self.engine)
        path = Path(__file__).parents[1] / "migrations/versions/025_growth_delivery_safety.py"
        spec = importlib.util.spec_from_file_location("growth_pg_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                migration.downgrade()
            inspector = inspect(connection)
            columns = {column["name"]: column for column in inspector.get_columns(
                "growth_deliveries", schema=self.schema)}
            self.assertTrue(columns["claimed_at"]["type"].timezone)
            self.assertTrue(columns["finished_at"]["type"].timezone)
            self.assertIn("uq_growth_delivery_recipient", {constraint["name"] for constraint in
                          inspector.get_unique_constraints("growth_deliveries", schema=self.schema)})
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(GrowthSend)).all()), 2)


if __name__ == "__main__":
    unittest.main()
