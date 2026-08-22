from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from jose import jwt
from sqlalchemy.pool import StaticPool
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.knowledge.client import _service_token, scoped_dealers
from app.knowledge.router import ExportBody, export_original
from app.database import init_db
from app.models.dealer_assignment import DealerAssignment
from app.models.dealer_store import DealerStore


class KnowledgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.secret = "knowledge-test-secret-at-least-32-bytes"
        self.settings = SimpleNamespace(
            knowledge_hub_token_key_file="",
            knowledge_hub_token_secret=self.secret,
            knowledge_hub_team_map={"overseas": "overseas-sales"},
        )
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(self.engine)
        self.dealer_a = str(uuid4())
        self.dealer_b = str(uuid4())
        with Session(self.engine) as session:
            session.add_all([
                User(
                    username="sales", hashed_password="x", role="sales", data_scope="self",
                    team_key="overseas", must_change_password=False,
                ),
                DealerStore(
                    store_id="a", name="Dealer A", team_key="overseas",
                    knowledge_dealer_id=self.dealer_a,
                ),
                DealerStore(
                    store_id="b", name="Dealer B", team_key="overseas",
                    knowledge_dealer_id=self.dealer_b,
                ),
            ])
            session.commit()
            user = session.exec(select(User).where(User.username == "sales")).one()
            session.add(DealerAssignment(user_id=user.id, store_id="a"))
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_service_token_contains_only_assigned_dealer_and_team(self):
        with Session(self.engine) as session, patch(
            "app.knowledge.client.get_settings", return_value=self.settings
        ):
            user = session.exec(select(User).where(User.username == "sales")).one()
            token = _service_token(user, session)
            payload = jwt.decode(
                token, self.secret, algorithms=["HS256"],
                audience="dealer-knowledge-hub", issuer="pdca-workbench",
            )
            self.assertEqual(payload["dealer_ids"], [self.dealer_a])
            self.assertEqual(payload["team_keys"], ["overseas-sales"])
            self.assertEqual(payload["scope"], "self")
            self.assertLessEqual(payload["exp"] - payload["iat"], 300)
            self.assertEqual(
                scoped_dealers(user, session),
                [{"store_id": "a", "name": "Dealer A", "dealer_id": self.dealer_a}],
            )

    def test_multiple_stores_for_one_dealer_are_deduplicated(self):
        with Session(self.engine) as session:
            session.add(DealerStore(
                store_id="a-branch", name="Dealer A · Branch", team_key="overseas",
                knowledge_dealer_id=self.dealer_a,
            ))
            session.commit()
            user = session.exec(select(User).where(User.username == "sales")).one()
            session.add(DealerAssignment(user_id=user.id, store_id="a-branch"))
            session.commit()
            self.assertEqual(len(scoped_dealers(user, session)), 1)

    def test_non_admin_cannot_reach_original_export(self):
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == "sales")).one()
            request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
            body = ExportBody(
                asset_id=uuid4(), reason="customer contract review", confirmation="export-original"
            )
            with patch("app.knowledge.router.request_content", new=AsyncMock()) as upstream:
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(export_original(body, request, user, session))
            self.assertEqual(caught.exception.status_code, 403)
            upstream.assert_not_awaited()

    def test_customer_profile_is_part_of_fresh_schema(self):
        with patch("app.database.get_engine", return_value=self.engine):
            init_db()
        self.assertIn("customer_profiles", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
