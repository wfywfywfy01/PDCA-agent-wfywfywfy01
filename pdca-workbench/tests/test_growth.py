"""Growth flywheel: generation, tracked email sending, tracking endpoints, reply polling."""
import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.growth import mailer, router as growth_router, service
from app.growth.models import GrowthAsset, GrowthContent, GrowthSend, GrowthUnsub

ENV = {
    "PDCA_GROWTH_SMTP_HOST": "smtp.test", "PDCA_GROWTH_SMTP_USER": "sales@vertu.test",
    "PDCA_GROWTH_SMTP_PASSWORD": "x", "PDCA_GROWTH_IMAP_HOST": "imap.test",
    "PDCA_GROWTH_DAILY_CAP": "2", "PDCA_GROWTH_PUBLIC_BASE": "https://pub.test",
}
SETTINGS = SimpleNamespace(secret_key="offline-test-key")


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        patch.dict(os.environ, ENV).start()
        patch("app.growth.mailer.get_settings", return_value=SETTINGS).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _email(self, body="Hi, see https://shop.test/p?x=1 now") -> GrowthContent:
        row = GrowthContent(round_no=1, kind="email", topic="t", variant="A",
                            title="Subject", body=body)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def test_generate_saves_variants_and_uses_dossier(self):
        self.session.add_all([GrowthAsset(kind="product", title="P1", body="Agent Q specs"),
                              GrowthAsset(kind="dossier", title="D1", body="Dubai dealer"),
                              GrowthAsset(kind="dossier", title="D2", body="Other dealer")])
        self.session.commit()
        reply = json.dumps({"variants": [{"angle": "craft", "title": "T1", "body": "B1"},
                                         {"angle": "margin", "title": "T2", "body": "B2"},
                                         {"angle": "x", "title": "empty", "body": ""}]})
        with patch.object(service, "_llm", return_value=reply) as llm:
            rows = service.generate(self.session, kind="email", topic="Agent Q",
                                    dealer_asset_id=2, variants=3)
            again = service.generate(self.session, kind="seo", topic="Agent Q", variants=1)
        prompt = llm.call_args_list[0].args[0][1]["content"]
        self.assertIn("Dubai dealer", prompt)
        self.assertNotIn("Other dealer", prompt)
        self.assertEqual([(r.variant, r.round_no) for r in rows], [("A", 1), ("B", 1)])
        self.assertEqual(again[0].round_no, 2)

    def test_parse_variants_accepts_fenced_json(self):
        self.assertEqual(len(service.parse_variants('```json\n{"variants":[{"body":"x"}]}\n```')), 1)

    def test_render_html_tracks_links_with_utm_and_escapes(self):
        content = self._email("Price <b> at https://shop.test/p?x=1")
        out = mailer.render_html(content, "tok")
        self.assertIn("&lt;b&gt;", out)
        self.assertIn("https://pub.test/api/growth/t/o/tok.gif", out)
        self.assertIn("/api/growth/t/u/tok", out)
        href = out.split('href="')[1].split('"')[0].replace("&amp;", "&")
        query = parse_qs(urlsplit(href).query)
        target = query["u"][0]
        self.assertIn("utm_campaign=growth-r1", target)
        self.assertIn("x=1", target)
        self.assertEqual(query["s"][0], mailer.sign("tok", target))

    def test_send_filters_and_respects_daily_cap(self):
        content = self._email()
        self.session.add(GrowthUnsub(email="gone@d.test"))
        self.session.commit()
        smtp = MagicMock()
        with patch("app.growth.mailer.smtplib.SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            result = mailer.send(self.session, content,
                                 ["A@d.test", "a@d.test", "bad", "gone@d.test", "b@d.test", "c@d.test"])
        self.assertEqual(result["sent"], ["a@d.test", "b@d.test"])
        self.assertIn("c@d.test", result["skipped"])
        self.assertIn("gone@d.test", result["skipped"])
        self.assertEqual(smtp.send_message.call_count, 2)
        msg = smtp.send_message.call_args.args[0]
        self.assertTrue(msg["List-Unsubscribe"].startswith("<https://pub.test/api/growth/t/u/"))
        self.assertFalse(msg.is_multipart())  # 默认纯文本、无像素
        self.assertIn(mailer.OPT_OUT, msg.get_content())
        self.assertEqual(self.session.get(GrowthContent, content.id).status, "sent")

    def test_send_with_tracking_adds_html_alternative(self):
        content = self._email()
        smtp = MagicMock()
        with patch("app.growth.mailer.smtplib.SMTP_SSL") as cls:
            cls.return_value.__enter__.return_value = smtp
            mailer.send(self.session, content, ["a@d.test"], track=True)
        msg = smtp.send_message.call_args.args[0]
        html_part = msg.get_body(("html",)).get_content()
        self.assertIn("/api/growth/t/o/", html_part)
        self.assertTrue(self.session.exec(select(GrowthSend)).one().tracked)

    def test_stop_loss_on_bounce_rate_and_low_reply(self):
        content = self._email()
        now = datetime.utcnow()
        self.session.add_all([
            GrowthSend(content_id=content.id, to_addr=f"x{i}@d.test", token=f"t{i}",
                       bounced_at=now if i < 2 else None) for i in range(20)])
        self.session.commit()
        with self.assertRaisesRegex(mailer.StopLoss, "退信率"):
            mailer.send(self.session, content, ["new@d.test"])
        other = self._email()
        self.session.add_all([
            GrowthSend(content_id=other.id, to_addr=f"y{i}@d.test", token=f"u{i}",
                       sent_at=now - timedelta(days=10)) for i in range(300)])
        self.session.commit()
        for row in self.session.exec(select(GrowthSend).where(GrowthSend.bounced_at.is_not(None))):
            row.bounced_at = None
            self.session.add(row)
        self.session.commit()
        with self.assertRaisesRegex(mailer.StopLoss, "回复率"):
            mailer.send(self.session, other, ["new@d.test"])
        self.assertEqual(self.session.get(GrowthContent, other.id).status, "paused")

    def test_tracking_endpoints(self):
        content = self._email()
        self.session.add(GrowthSend(content_id=content.id, to_addr="a@d.test", token="tok",
                                    message_id="<m1@x>", tracked=True))
        self.session.commit()
        app = FastAPI()
        app.include_router(growth_router.router)

        def local_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = local_session
        client = TestClient(app, follow_redirects=False)
        self.assertEqual(client.get("/api/growth/t/o/tok.gif").headers["content-type"], "image/gif")
        target = "https://shop.test/p"
        ok = client.get("/api/growth/t/c/tok", params={"u": target, "s": mailer.sign("tok", target)})
        self.assertEqual((ok.status_code, ok.headers["location"]), (302, target))
        bad = client.get("/api/growth/t/c/tok", params={"u": "https://evil.test", "s": "nope"})
        self.assertEqual(bad.status_code, 400)
        client.get("/api/growth/t/u/tok")
        with Session(self.engine) as s:
            row = s.exec(select(GrowthSend)).one()
            self.assertEqual((row.open_count, row.click_count), (1, 1))
            self.assertIsNotNone(s.get(GrowthUnsub, "a@d.test"))
        stats = asyncio.run(growth_router.stats(None, self.session))
        self.assertEqual(stats["rows"][0]["open_rate"], 1.0)
        self.assertEqual(stats["rows"][0]["reply_rate"], 0.0)

    def test_poll_replies_classifies_reply_bounce_ooo_unsub(self):
        content = self._email()
        self.session.add_all([
            GrowthSend(content_id=content.id, to_addr=f"{n}@d.test", token=n, message_id=f"<{n}@x>")
            for n in ("reply", "bounce", "ooo", "unsub", "quiet")])
        self.session.commit()

        def msg(headers: bytes, text: bytes = b"") -> tuple:
            return ("OK", [(b"1 (BODY[HEADER]", headers + b"\r\n"), (b"BODY[TEXT]", text), b")"])

        imap = MagicMock()
        imap.search.return_value = ("OK", [b"1 2 3 4"])
        imap.fetch.side_effect = [
            msg(b"From: a@d.test\r\nIn-Reply-To: <reply@x>\r\n", b"Sounds interesting, send specs"),
            msg(b"From: MAILER-DAEMON@mx.test\r\n", b"Original-Message-ID: <bounce@x>"),
            msg(b"From: c@d.test\r\nSubject: Automatic reply: hi\r\nIn-Reply-To: <ooo@x>\r\n"),
            msg(b"From: d@d.test\r\nIn-Reply-To: <unsub@x>\r\n", b"no\r\n\r\n> original"),
        ]
        with patch("app.growth.mailer.imaplib.IMAP4_SSL") as cls:
            cls.return_value.__enter__.return_value = imap
            self.assertEqual(mailer.poll_replies(self.session), 3)
        imap.select.assert_called_with("INBOX", readonly=True)
        rows = {r.token: r for r in self.session.exec(select(GrowthSend))}
        self.assertEqual(rows["reply"].reply_kind, "reply")
        self.assertIsNotNone(rows["bounce"].bounced_at)
        self.assertIsNone(rows["ooo"].replied_at)
        self.assertEqual(rows["unsub"].reply_kind, "unsub")
        self.assertIsNotNone(self.session.get(GrowthUnsub, "unsub@d.test"))
        self.assertIsNone(rows["quiet"].replied_at)


if __name__ == "__main__":
    unittest.main()
