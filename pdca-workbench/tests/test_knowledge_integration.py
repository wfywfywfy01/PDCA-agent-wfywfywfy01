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
from app.admin.router import StoreCreateBody, StoreUpdateBody, create_store, update_store
from app.knowledge.client import _service_token, scoped_dealers
from app.knowledge.router import ExportBody, QueryBody, export_original, search_knowledge
from app.database import init_db
from app.models.dealer_assignment import DealerAssignment
from app.models.dealer_store import DealerStore
from app.models.store_seed import seed_stores


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
                User(
                    username="manager", hashed_password="x", role="manager", data_scope="team",
                    team_key="overseas", must_change_password=False,
                ),
                User(
                    username="unmapped-manager", hashed_password="x", role="manager",
                    data_scope="team", team_key="unmapped", must_change_password=False,
                ),
                User(
                    username="unassigned", hashed_password="x", role="sales", data_scope="self",
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

    def test_sales_service_token_contains_only_assigned_dealer(self):
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
            self.assertEqual(payload["team_keys"], [])
            self.assertEqual(payload["scope"], "self")
            self.assertLessEqual(payload["exp"] - payload["iat"], 300)
            self.assertEqual(
                scoped_dealers(user, session),
                [{"store_id": "a", "name": "Dealer A", "dealer_id": self.dealer_a}],
            )

    def test_team_scope_uses_explicit_mapping_without_raw_fallback(self):
        with Session(self.engine) as session, patch(
            "app.knowledge.client.get_settings", return_value=self.settings
        ):
            mapped = session.exec(select(User).where(User.username == "manager")).one()
            unmapped = session.exec(
                select(User).where(User.username == "unmapped-manager")
            ).one()
            mapped_payload = jwt.decode(
                _service_token(mapped, session), self.secret, algorithms=["HS256"],
                audience="dealer-knowledge-hub", issuer="pdca-workbench",
            )
            unmapped_payload = jwt.decode(
                _service_token(unmapped, session), self.secret, algorithms=["HS256"],
                audience="dealer-knowledge-hub", issuer="pdca-workbench",
            )
            self.assertEqual(mapped_payload["team_keys"], ["overseas-sales"])
            self.assertEqual(unmapped_payload["team_keys"], [])

    def test_manager_cannot_change_knowledge_dealer_mapping(self):
        with Session(self.engine) as session:
            manager = session.exec(select(User).where(User.username == "manager")).one()
            with self.assertRaises(HTTPException) as create_error:
                asyncio.run(create_store(
                    StoreCreateBody(
                        store_id="new", name="New Dealer", region="其他",
                        knowledge_dealer_id=self.dealer_b,
                    ),
                    manager,
                    session,
                ))
            self.assertEqual(create_error.exception.status_code, 403)
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(update_store(
                    "a", StoreUpdateBody(knowledge_dealer_id=self.dealer_b), manager, session
                ))
            self.assertEqual(caught.exception.status_code, 403)
            with patch("app.admin.router.log_action"), patch(
                "app.auth.scope.rebuild_all_dealer_assignments"
            ):
                asyncio.run(update_store(
                    "a", StoreUpdateBody(name="Dealer A updated"), manager, session
                ))
            store = session.exec(select(DealerStore).where(DealerStore.store_id == "a")).one()
            self.assertEqual(store.knowledge_dealer_id, self.dealer_a)
            self.assertEqual(store.name, "Dealer A updated")

    def test_empty_and_out_of_scope_queries_fail_before_proxy(self):
        request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
        with Session(self.engine) as session, patch(
            "app.knowledge.router.request_json", new=AsyncMock()
        ) as upstream:
            unassigned = session.exec(select(User).where(User.username == "unassigned")).one()
            sales = session.exec(select(User).where(User.username == "sales")).one()
            for user, dealer_id in ((unassigned, None), (sales, self.dealer_b)):
                with self.subTest(user=user.username):
                    with self.assertRaises(HTTPException) as caught:
                        asyncio.run(search_knowledge(
                            QueryBody(query="contract", dealer_id=dealer_id), request, user, session
                        ))
                    self.assertEqual(caught.exception.status_code, 403)
            upstream.assert_not_awaited()

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

    def test_seed_preserves_existing_owner_and_fills_blank_vmg_owner(self):
        with Session(self.engine) as session:
            session.add_all([
                DealerStore(
                    store_id="sea02a", name="VMG custom", region="其他", country="",
                    sales_owner="custom-owner",
                ),
                DealerStore(
                    store_id="sea02b", name="VMG blank", region="其他", country="",
                    sales_owner="",
                ),
            ])
            session.commit()
        with patch("app.models.store_seed.get_engine", return_value=self.engine):
            seed_stores()
        with Session(self.engine) as session:
            custom = session.exec(
                select(DealerStore).where(DealerStore.store_id == "sea02a")
            ).one()
            blank = session.exec(
                select(DealerStore).where(DealerStore.store_id == "sea02b")
            ).one()
            self.assertEqual(custom.sales_owner, "custom-owner")
            self.assertEqual(blank.sales_owner, "尤文静")


if __name__ == "__main__":
    unittest.main()
