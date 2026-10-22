"""Offline delivery and reply regressions. Never connects to a real mailbox."""
import importlib.util
import os
import smtplib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import SQLModel, Session, create_engine, select

from app.growth import mailer, models
from app.growth.models import GrowthContent, GrowthSend, GrowthUnsub


class GrowthMailSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="growth_mail_test_")
        self.engine = create_engine("sqlite:///" + (Path(self.tmp.name) / "mail.db").as_posix(),
                                    connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.content = GrowthContent(round_no=1, kind="email", topic="t", variant="A",
                                     title="Subject", body="Hello")
        self.db.add(self.content)
        self.db.commit()
        self.cid = self.content.id
        self.env = patch.dict(os.environ, {
            "PDCA_GROWTH_SMTP_HOST": "smtp.test", "PDCA_GROWTH_SMTP_PORT": "465",
            "PDCA_GROWTH_SMTP_USER": "sender@example.test", "PDCA_GROWTH_SMTP_PASSWORD": "offline",
            "PDCA_GROWTH_IMAP_HOST": "imap.test", "PDCA_GROWTH_DAILY_CAP": "1",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _record(self, **kw):
        row = GrowthSend(content_id=self.cid, to_addr="client@example.test", token="token",
                         message_id="<original@example.test>", **kw)
        self.db.add(row)
        self.db.commit()
        return row

    def _poll(self, body, headers=b""):
        imap = MagicMock()
        imap.search.return_value = ("OK", [b"1"])
        head = b"From: client@example.test\r\nIn-Reply-To: <original@example.test>\r\n" + headers
        imap.fetch.return_value = ("OK", [(b"BODY[HEADER]", head + b"\r\n"),
                                          (b"BODY[TEXT]", body), b")"])
        with patch.object(mailer.imaplib, "IMAP4_SSL") as cls:
            cls.return_value.__enter__.return_value = imap
            return mailer.poll_replies(self.db)

    def test_positive_reply_does_not_unsubscribe_quoted_tracking_footer(self):
        row = self._record()
        self.assertEqual(self._poll(
            b'<p>Yes, send pricing.</p><blockquote><a href="https://test/unsub">unsubscribe</a></blockquote>',
            b"Content-Type: text/html; charset=utf-8\r\n"), 1)
        self.db.refresh(row)
        self.assertEqual(row.reply_kind, "reply")
        self.assertIsNone(self.db.get(GrowthUnsub, row.to_addr))

    def test_mime_base64_unsubscribe_is_decoded(self):
        row = self._record()
        self._poll(b"bm8=\r\n", b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n")
        self.db.refresh(row)
        self.assertEqual(row.reply_kind, "unsub")
        self.assertIsNotNone(self.db.get(GrowthUnsub, row.to_addr))

    def test_self_closing_html_inside_quote_does_not_expose_original_footer(self):
        row = self._record()
        self._poll(b'<p>Yes, send pricing.</p><blockquote>Original<br/><a>unsubscribe</a></blockquote>',
                   b"Content-Type: text/html; charset=utf-8\r\n")
        self.db.refresh(row)
        self.assertEqual(row.reply_kind, "reply")

    def test_later_unsubscribe_on_old_replied_thread_is_processed_idempotently(self):
        row = self._record(replied_at=datetime.now(timezone.utc) - timedelta(days=20),
                           sent_at=datetime.now(timezone.utc) - timedelta(days=30), reply_kind="reply")
        self.assertEqual(self._poll(b"no\r\n"), 1)
        self.assertEqual(self._poll(b"no\r\n"), 0)
        self.db.refresh(row)
        self.assertEqual(row.reply_kind, "unsub")
        self.assertIsNotNone(self.db.get(GrowthUnsub, row.to_addr))
        self._poll(b"Thanks")
        self.db.refresh(row)
        self.assertEqual(row.reply_kind, "unsub")

    def _unconfirmed_unsubscribe(self, status):
        claim = models.GrowthDelivery(content_id=self.cid, to_addr="client@example.test", status=status,
                                       token="unconfirmed", message_id="<original@example.test>")
        self.db.add(claim)
        self.db.commit()
        self.assertEqual(self._poll(b"no\r\n"), 1)
        self.assertEqual(self._poll(b"no\r\n"), 0)
        self.assertIsNotNone(self.db.get(GrowthUnsub, claim.to_addr))
        self.db.refresh(claim)
        self.assertEqual(claim.status, status)
        self.assertEqual(self.db.exec(select(GrowthSend)).all(), [])

    def test_pending_delivery_can_be_unsubscribed_by_reply(self):
        self._unconfirmed_unsubscribe("pending")

    def test_uncertain_delivery_can_be_unsubscribed_by_reply(self):
        self._unconfirmed_unsubscribe("uncertain")

    def _concurrent_sends(self, same_address):
        ready, release = threading.Event(), threading.Event()
        start = threading.Barrier(2)
        smtp = MagicMock()
        def fake_send(message):
            ready.set()
            self.assertTrue(release.wait(5))
            return {}
        smtp.send_message.side_effect = fake_send
        def worker(index):
            with Session(self.engine) as db:
                content = db.get(GrowthContent, self.cid)
                start.wait(5)
                addr = "client@example.test" if same_address else f"client{index}@example.test"
                return mailer.send(db, content, [addr])
        with patch.object(mailer.smtplib, "SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, n) for n in range(2)]
                try:
                    self.assertTrue(ready.wait(5))
                    wait(futures, timeout=0.3)
                finally:
                    release.set()
                results = [f.result() for f in futures]
        self.assertEqual(smtp.send_message.call_count, 1)
        self.assertEqual(sum(len(r["sent"]) for r in results), 1)
        self.assertEqual(len(self.db.exec(select(GrowthSend)).all()), 1)

    def test_concurrent_identical_request_sends_once(self):
        self._concurrent_sends(True)

    def test_concurrent_different_recipients_share_daily_cap(self):
        self._concurrent_sends(False)

    def test_ambiguous_smtp_failure_is_persisted_and_not_retried(self):
        smtp = MagicMock()
        smtp.send_message.side_effect = smtplib.SMTPServerDisconnected("reply lost after DATA")
        with patch.object(mailer.smtplib, "SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            first = mailer.send(self.db, self.content, ["client@example.test"])
            second = mailer.send(self.db, self.content, ["client@example.test"])
        self.assertEqual(first.get("uncertain"), ["client@example.test"])
        self.assertEqual(second.get("uncertain"), ["client@example.test"])
        self.assertEqual(smtp.send_message.call_count, 1)
        self.assertEqual(self.db.exec(select(models.GrowthDelivery)).one().status, "uncertain")
        self.assertEqual(self.db.exec(select(GrowthSend)).all(), [])

    def test_process_crash_leaves_pending_claim_that_blocks_retry(self):
        smtp = MagicMock()
        smtp.send_message.side_effect = KeyboardInterrupt("simulate process death")
        with patch.object(mailer.smtplib, "SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            with self.assertRaises(KeyboardInterrupt):
                mailer.send(self.db, self.content, ["client@example.test"])
            smtp.send_message.side_effect = None
            smtp.send_message.return_value = {}
            result = mailer.send(self.db, self.content, ["client@example.test"])
        self.assertEqual(result.get("pending"), ["client@example.test"])
        self.assertEqual(smtp.send_message.call_count, 1)

    def test_explicit_rejection_is_failed_and_keeps_claim(self):
        smtp = MagicMock()
        smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused({"client@example.test": (550, b"rejected")})
        with patch.object(mailer.smtplib, "SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            result = mailer.send(self.db, self.content, ["client@example.test"])
            mailer.send(self.db, self.content, ["client@example.test"])
        self.assertEqual(result["failed"], ["client@example.test"])
        self.assertEqual(smtp.send_message.call_count, 1)
        self.assertEqual(self.db.exec(select(models.GrowthDelivery)).one().status, "failed")

    def test_failed_outcome_commit_does_not_make_successful_smtp_retryable(self):
        smtp = MagicMock()
        smtp.send_message.return_value = {}
        with patch.object(mailer.smtplib, "SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            with patch.object(mailer, "_finish_delivery", side_effect=SQLAlchemyError("db unavailable")):
                result = mailer.send(self.db, self.content, ["client@example.test"])
            retry = mailer.send(self.db, self.content, ["client@example.test"])
        self.assertEqual(result["uncertain"], ["client@example.test"])
        self.assertEqual(retry["pending"], ["client@example.test"])
        self.assertEqual(smtp.send_message.call_count, 1)
        self.assertEqual(self.db.exec(select(GrowthSend)).all(), [])
        self.assertEqual(self.db.exec(select(models.GrowthDelivery)).one().status, "pending")

    def test_quota_cannot_lose_claim_during_pending_to_sent_transition(self):
        claim = models.GrowthDelivery(content_id=self.cid, to_addr="client@example.test",
                                       token="race", message_id="<race@example.test>")
        self.db.add(claim)
        self.db.commit()
        changed = False
        def finish_between_count_reads(conn, cursor, statement, parameters, context, executemany):
            nonlocal changed
            if changed or not statement.lstrip().startswith("SELECT") or "growth_deliveries" not in statement:
                return
            changed = True
            with Session(self.engine) as other:
                active = other.exec(select(models.GrowthDelivery)).one()
                active.status = "sent"
                other.add(active)
                other.add(GrowthSend(content_id=self.cid, to_addr=active.to_addr, token=active.token,
                                     message_id=active.message_id, sent_at=active.claimed_at))
                other.commit()
        event.listen(self.engine, "before_cursor_execute", finish_between_count_reads)
        try:
            self.assertEqual(mailer.quota_used_today(self.db), 1)
        finally:
            event.remove(self.engine, "before_cursor_execute", finish_between_count_reads)
        self.assertTrue(changed)

    def test_migration_preserves_duplicate_history_and_is_idempotent(self):
        self._record()
        self.db.add(GrowthSend(content_id=self.cid, to_addr="client@example.test", token="duplicate"))
        self.db.commit()
        path = Path(__file__).parents[1] / "migrations/versions/025_growth_delivery_safety.py"
        spec = importlib.util.spec_from_file_location("growth_delivery_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.db.close()
        models.GrowthDelivery.__table__.drop(self.engine)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
            self.assertTrue(inspect(connection).has_table("growth_deliveries"))
        self.assertEqual(len(self.db.exec(select(GrowthSend)).all()), 2)


if __name__ == "__main__":
    unittest.main()
