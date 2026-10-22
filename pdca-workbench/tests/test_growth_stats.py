"""Visible delivery state and rates must reflect confirmed outcomes."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.growth import router
from app.growth.models import GrowthContent, GrowthDelivery, GrowthSend, GrowthUnsub


class GrowthStatsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.content = GrowthContent(round_no=1, kind="email", topic="test", variant="A", body="body")
        self.session.add(self.content)
        self.session.commit()

    def test_unresolved_delivery_stays_visible_across_days(self):
        now = datetime.now(timezone.utc)
        for status, age in (("pending", 0), ("uncertain", 2)):
            self.session.add(GrowthDelivery(content_id=self.content.id, to_addr=f"{status}@example.test",
                status=status, token=status, message_id=f"<{status}@example.test>",
                claimed_at=now - timedelta(days=age)))
        self.session.commit()
        result = asyncio.run(router.stats(None, self.session))
        self.assertEqual(result.get("pending_total"), 1)
        self.assertEqual(result.get("uncertain_total"), 1)
        self.assertEqual(result["sent_today"], 0)
        self.assertEqual(result.get("quota_used_today"), 1)
        self.assertEqual(len(result.get("unresolved", [])), 2)
        self.assertEqual(result["unresolved"][0]["message_id"], "<pending@example.test>")
        self.assertTrue(result["unresolved"][0]["claimed_at"].endswith("+00:00"))

    def test_click_unsubscribe_is_idempotently_counted(self):
        self.session.add(GrowthSend(content_id=self.content.id, to_addr="client@example.test", token="token"))
        self.session.commit()
        for _ in range(2):
            asyncio.run(router.track_unsub("token", self.session))
        result = asyncio.run(router.stats(None, self.session))
        self.assertEqual(result["rows"][0]["unsub"], 1)
        self.assertEqual(result["rows"][0]["replied"], 0)
        self.assertIsNotNone(self.session.get(GrowthUnsub, "client@example.test"))

    def test_tracking_rates_exclude_bounced_deliveries(self):
        now = datetime.now(timezone.utc)
        self.session.add_all([
            GrowthSend(content_id=self.content.id, to_addr="ok@example.test", token="ok", tracked=True,
                       opened_at=now, clicked_at=now),
            GrowthSend(content_id=self.content.id, to_addr="bad@example.test", token="bad", tracked=True,
                       bounced_at=now),
        ])
        self.session.commit()
        result = asyncio.run(router.stats(None, self.session))
        self.assertEqual(result["rows"][0]["open_rate"], 1)
        self.assertEqual(result["rows"][0]["click_rate"], 1)

    def test_unsubscribe_works_when_smtp_outcome_is_not_confirmed(self):
        for status in ("pending", "uncertain"):
            with self.subTest(status=status):
                address = f"{status}@example.test"
                self.session.add(GrowthDelivery(content_id=self.content.id, to_addr=address,
                    status=status, token=status, message_id=f"<{status}@example.test>"))
                self.session.commit()
                for _ in range(2):
                    asyncio.run(router.track_unsub(status, self.session))
                self.assertIsNotNone(self.session.get(GrowthUnsub, address))


if __name__ == "__main__":
    unittest.main()
