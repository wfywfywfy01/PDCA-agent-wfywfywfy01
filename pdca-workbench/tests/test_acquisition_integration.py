from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.acquisition.service import consume_login_ticket, issue_login_ticket
from app.auth.models import User
from app.auth.scope import DataScope
from app.models.acquisition_login_ticket import AcquisitionLoginTicket
from app.pages.router import _customer_acquisition_page


class AcquisitionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_ticket_is_scoped_and_single_use(self):
        user = User(id=17, username="april", hashed_password="test", display_name="April", role="sales", owner_key="april")
        self.session.add(user)
        self.session.commit()
        scope = DataScope(
            mode="self",
            store_ids=("store-april",),
            dealer_names=("April Dealer",),
            owner_keys=("april", "April"),
            team_key="overseas-a",
        )

        code = issue_login_ticket(user, scope, self.session)
        profile = consume_login_ticket(code, self.session)

        self.assertEqual(profile, {
            "subject": "pdca:17",
            "username": "april",
            "display_name": "April",
            "role": "sales",
            "data_scope": "self",
            "owner_key": "april",
            "team_key": "overseas-a",
            "owner_keys": ["april", "April"],
        })
        with self.assertRaises(HTTPException) as replay:
            consume_login_ticket(code, self.session)
        self.assertEqual(replay.exception.status_code, 401)

    def test_expired_ticket_is_rejected(self):
        user = User(id=18, username="sales", hashed_password="test", display_name="Sales", role="sales")
        self.session.add(user)
        self.session.commit()
        code = issue_login_ticket(user, DataScope("self", (), (), ()), self.session)
        ticket = self.session.exec(select(AcquisitionLoginTicket)).first()
        ticket.expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.session.add(ticket)
        self.session.commit()

        with self.assertRaises(HTTPException) as expired:
            consume_login_ticket(code, self.session)
        self.assertEqual(expired.exception.status_code, 401)

    def test_deactivated_user_cannot_exchange_issued_ticket(self):
        user = User(id=19, username="disabled", hashed_password="test", display_name="Disabled", role="sales")
        self.session.add(user)
        self.session.commit()
        code = issue_login_ticket(user, DataScope("self", (), (), ()), self.session)
        user.is_active = False
        self.session.add(user)
        self.session.commit()

        with self.assertRaises(HTTPException) as disabled:
            consume_login_ticket(code, self.session)
        self.assertEqual(disabled.exception.status_code, 401)

    def test_embed_page_keeps_legacy_fallback_and_escapes_url(self):
        response = _customer_acquisition_page(
            'https://global-autoleads.vertu.cn/?pdca_code=x&next="bad"',
            "2026-07-20",
        )
        body = response.body.decode("utf-8")

        self.assertIn("/customer-mgmt?legacy=1", body)
        self.assertIn("自动化获客与客户管理", body)
        self.assertIn('next=&quot;bad&quot;', body)
        self.assertNotIn('next="bad"', body)


if __name__ == "__main__":
    unittest.main()
