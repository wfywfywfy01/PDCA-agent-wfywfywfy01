from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from app.auth.models import User
from app.auth.security import create_access_token
from app.knowledge.mcp import (
    PDCATokenVerifier,
    knowledge_mcp_app,
    list_dealers,
    search_dealer_knowledge,
)
from app.models.dealer_assignment import DealerAssignment
from app.models.dealer_store import DealerStore


class KnowledgeMcpTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.dealer_id = str(uuid4())
        with Session(self.engine) as session:
            user = User(
                username="viki",
                hashed_password="x",
                role="sales",
                data_scope="self",
                team_key="overseas",
                pwd_version=2,
                must_change_password=False,
            )
            session.add_all([
                user,
                DealerStore(
                    store_id="iran",
                    name="Safiran Hamrah",
                    team_key="overseas",
                    knowledge_dealer_id=self.dealer_id,
                ),
            ])
            session.commit()
            session.refresh(user)
            session.add(DealerAssignment(user_id=user.id, store_id="iran"))
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_transport_requires_auth_and_lists_tools_for_valid_token(self):
        token = create_access_token(
            {"sub": "viki", "role": "sales", "pwd_v": 2},
            timedelta(minutes=5),
        )
        with (
            patch("app.knowledge.mcp.get_engine", return_value=self.engine),
            TestClient(knowledge_mcp_app) as client,
        ):
            denied = client.post(
                "/",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            response = client.post(
                "/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {tool["name"] for tool in response.json()["result"]["tools"]},
            {"list_dealers", "search_dealer_knowledge", "answer_dealer_question"},
        )

    def test_verifier_rejects_stale_password_version(self):
        verifier = PDCATokenVerifier()
        with (
            patch("app.knowledge.mcp.get_engine", return_value=self.engine),
            patch("app.knowledge.mcp.is_token_revoked", return_value=False),
            patch(
                "app.knowledge.mcp.decode_token",
                return_value={"sub": "viki", "pwd_v": 1, "exp": 2_000_000_000},
            ),
        ):
            access = asyncio.run(verifier.verify_token("token"))
        self.assertIsNone(access)

    def test_tools_use_existing_dealer_scope(self):
        access = SimpleNamespace(subject="viki")
        upstream = AsyncMock(return_value={"items": [{"text": "evidence"}]})
        with (
            patch("app.knowledge.mcp.get_engine", return_value=self.engine),
            patch("app.knowledge.mcp.get_access_token", return_value=access),
            patch("app.knowledge.mcp.request_json", new=upstream),
        ):
            visible = asyncio.run(list_dealers())
            result = asyncio.run(search_dealer_knowledge(
                "Safiran Hamrah 库存",
                dealer_id=self.dealer_id,
            ))

        self.assertEqual(visible["dealers"][0]["name"], "Safiran Hamrah")
        self.assertEqual(result["items"][0]["text"], "evidence")
        self.assertEqual(upstream.await_args.kwargs["body"]["dealer_id"], self.dealer_id)
        self.assertTrue(upstream.await_args.kwargs["request_id"].startswith("mcp-"))

    def test_tool_rejects_dealer_outside_sales_scope(self):
        access = SimpleNamespace(subject="viki")
        upstream = AsyncMock()
        with (
            patch("app.knowledge.mcp.get_engine", return_value=self.engine),
            patch("app.knowledge.mcp.get_access_token", return_value=access),
            patch("app.knowledge.mcp.request_json", new=upstream),
            self.assertRaises(HTTPException) as caught,
        ):
            asyncio.run(search_dealer_knowledge(
                "contract",
                dealer_id=str(uuid4()),
            ))
        self.assertEqual(caught.exception.status_code, 403)
        upstream.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
