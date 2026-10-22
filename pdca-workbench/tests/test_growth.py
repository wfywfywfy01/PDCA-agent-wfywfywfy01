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

    def test_fetcher_parses_sitemap_and_article(self):
        from app.growth import fetcher
        sm = ("<urlset><url><loc>https://vertu.com/a/x</loc>"
              "<lastmod>2026-10-20T00:00:00Z</lastmod></url></urlset>")
        art = ("<html><head><title>T &amp; co</title>"
               "<meta name='description' content='Desc'></head>"
               "<body><script>junk()</script><h1>Hi</h1><p>world</p></body></html>")

        def fake_get(path, timeout=20):
            return (200, sm) if "sitemap" in path else (200, art)

        with patch.object(fetcher, "_get", side_effect=fake_get):
            posts = fetcher.list_posts()
            post = fetcher.fetch_post("https://vertu.com/a/x")
        self.assertEqual((posts[0]["slug"], posts[0]["lastmod"]), ("x", "2026-10-20"))
        self.assertEqual((post["title"], post["meta"]), ("T &amp; co", "Desc"))
        self.assertIn("world", post["text"])
        self.assertNotIn("junk", post["text"])

    def test_seo_review_fix_and_ideas(self):
        from app.growth import fetcher
        fix = json.dumps({"variants": [{"angle": "a", "title": "New Title", "body": "brief"}]})
        idea = json.dumps({"variants": [{"angle": "a1", "title": "q1", "body": "o1"},
                                        {"angle": "a2", "title": "q2", "body": "o2"}]})
        art = {"url": "u", "status": 200, "title": "T", "meta": "M", "words": 9, "text": "page body"}
        with patch.object(fetcher, "fetch_post", return_value=art), \
                patch.object(service, "_llm", return_value=fix) as llm:
            rows = service.seo_review(self.session, urls=["https://vertu.com/a/x"],
                                      table="query,clicks\nx,5")
        self.assertEqual((rows[0].kind, rows[0].topic), ("seo_fix", "https://vertu.com/a/x"))
        prompt = llm.call_args.args[0][1]["content"]
        self.assertIn("page body", prompt)
        self.assertIn("query,clicks", prompt)
        with patch.object(fetcher, "list_posts", return_value=[{"url": "u1", "lastmod": "", "slug": "old"}]), \
                patch.object(service, "_llm", return_value=idea):
            ideas = service.seo_review(self.session, urls=None, table="t", ideas=2)
        self.assertEqual([(r.kind, r.variant) for r in ideas],
                         [("seo_idea", "A"), ("seo_idea", "B")])
        self.assertEqual(ideas[0].round_no, rows[0].round_no + 1)

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

    def test_plain_body_fills_sender_and_postal_address(self):
        content = self._email("Hi\n\n{{sender_name}}")
        with patch.dict(os.environ, {"PDCA_GROWTH_SENDER_NAME": r"Frank Foo\nDealer Network Development Manager, Europe\nVERTU",
                                     "PDCA_GROWTH_POSTAL_ADDRESS": "Room 505, Kowloon, Hong Kong"}):
            body = mailer.plain_body(content)
        self.assertIn("Frank Foo\nDealer Network Development Manager, Europe\nVERTU", body)
        self.assertNotIn("{{sender_name}}", body)
        self.assertTrue(body.rstrip().endswith("Room 505, Kowloon, Hong Kong"))
        self.assertTrue(body.startswith("Hi\n\nFrank Foo"))

    def test_plain_body_moves_inline_signature_to_own_paragraph(self):
        with patch.dict(os.environ, {"PDCA_GROWTH_SENDER_NAME": "Frank Foo"}):
            body = mailer.plain_body(self._email("Worth a chat? {{sender_name}}"))
        self.assertTrue(body.startswith("Worth a chat?\n\nFrank Foo"))

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
            msg("From: 张三 <a@d.test>\r\nIn-Reply-To: <reply@x>\r\n".encode(), b"Sounds interesting, send specs"),
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

    def test_ga4_briefing_joins_unpublished_topic(self):
        from app.growth import ga4
        top = [{"page": "/lifestyle/price", "views": 100, "sessions": 80, "users": 70,
                "engRate": 0.7, "keyEvents": 0}]
        partners = [{"page": "//news/partners/live-post", "views": 4, "sessions": 3, "users": 3,
                     "engRate": 0.5, "keyEvents": 0},
                    {"page": "/news/partners/live-post", "views": 1, "sessions": 1, "users": 1,
                     "engRate": 1, "keyEvents": 0}]
        topics = "title\turl\nLive\thttps://vertu.com/news/partners/live-post\nDraft\t\n"
        with self._topics(topics), \
                patch.dict(os.environ, {"PDCA_GROWTH_GA4_SNAPSHOT": ""}), \
                patch.object(ga4, "content_rows", return_value=top), \
                patch.object(ga4, "path_rows", return_value=partners):
            out = ga4.briefing(28, force=True)
        self.assertEqual(out["topics"], 2)
        self.assertIn("/lifestyle/price\t100\t80\t70\t0.7\t0", out["table"])
        self.assertIn("Live\thttps://vertu.com/news/partners/live-post\t5\t4\t0.5", out["table"])
        self.assertIn("Draft\t(not published)", out["table"])

    def test_ga4_briefing_uses_snapshot_when_google_unreachable(self):
        import tempfile

        from app.growth import ga4
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json")
        json.dump({"days": 28, "top": 1, "topics": 2, "table": "cached-table"}, fh)
        fh.close()
        self.addCleanup(os.remove, fh.name)
        with patch.dict(os.environ, {"PDCA_GROWTH_GA4_SNAPSHOT": fh.name}), \
                patch.object(ga4, "content_rows", side_effect=ga4.Ga4Error("down")):
            out = ga4.briefing()
        self.assertTrue(out["stale"])
        self.assertEqual(out["table"], "cached-table")
        self.assertIsNotNone(out["age_hours"])

    def test_sync_topics_from_sheet_keeps_unpublished_blank(self):
        import importlib.util

        path = os.path.join(os.path.dirname(__file__), "..", "scripts", "sync_ga4_snapshot.py")
        spec = importlib.util.spec_from_file_location("sync_ga4_snapshot", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = mod._topics_from_sheet({
            "workbook": {"sheets": {"s": {"cellData": {
                "0": {"1": {"v": "选题"}, "7": {"v": "线上url"}},
                "1": {"1": {"v": "已发"}, "7": {"v": "https://vertu.com/a"}},
                "2": {"1": {"v": "未发"}, "7": {"v": ""}},
            }}}}
        })
        self.assertIn("已发\thttps://vertu.com/a", text)
        self.assertIn("未发\t\n", text)

    def test_seo_review_uses_ga4_when_table_empty(self):
        from app.growth import fetcher, ga4
        idea = json.dumps({"variants": [{"angle": "a", "title": "q", "body": "outline"}]})
        with patch.object(ga4, "configured", return_value=True), \
                patch.object(ga4, "briefing", return_value={"table": "page\tviews\n/price\t9"}), \
                patch.object(fetcher, "list_posts", return_value=[]), \
                patch.object(service, "_llm", return_value=idea) as llm:
            rows = service.seo_review(self.session, urls=None, table="", ideas=1)
        self.assertEqual(rows[0].kind, "seo_idea")
        self.assertIn("/price", llm.call_args.args[0][1]["content"])

    def _topics(self, text: str):
        import tempfile
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".tsv")
        fh.write(text)
        fh.close()
        self.addCleanup(os.remove, fh.name)
        return patch.dict(os.environ, {"PDCA_GROWTH_SEO_TOPICS_FILE": fh.name})


if __name__ == "__main__":
    unittest.main()
