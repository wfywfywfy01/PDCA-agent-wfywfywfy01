import asyncio
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.auth import router as auth
from app.auth.models import User
from app.auth.security import decode_access_token, decode_token
from app.database import get_session
from app.mcp_five_kit import FiveKitTokenVerifier


class WorkbenchFiveKitSessionTest(unittest.TestCase):
    def test_grant_is_bound_and_usable_only_for_five_kit(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        tmp_path = Path(directory.name)
        engine = create_engine(f"sqlite:///{(tmp_path / 'oauth.db').as_posix()}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(User(username="sales", hashed_password="fixture", role="sales", vps_user_id=23,
                             is_active=True, must_change_password=False))
            session.commit()

        def get_test_session():
            with Session(engine) as session:
                yield session

        app = FastAPI()
        app.include_router(auth.router)
        app.dependency_overrides[get_session] = get_test_session
        url = auth._WORKBENCH_ORIGIN
        cookie = "x" * 43
        request = httpx.Request("GET", f"{url}/gtm/api/me")
        upstream = MagicMock()
        upstream.__aenter__.return_value.get = AsyncMock()
        get = upstream.__aenter__.return_value.get
        headers = {"Origin": url, "X-WorkBench-Source": "pdca-five-kit"}
        client = TestClient(app, cookies={"salesbot_session": cookie})
        route = "/api/auth/workbench-five-kit"

        def identity(directory_id):
            user = {"must_change_password": False}
            if directory_id is not None:
                user["vps_directory_user_id"] = directory_id
            return httpx.Response(200, json={"ok": True, "data": {"user": user}}, request=request)

        with patch("app.auth.router.httpx.AsyncClient", return_value=upstream):
            assert client.post(route, headers={**headers, "Origin": "https://other.example"}).status_code == 403
            assert TestClient(app).post(route, headers=headers).status_code == 401
            get.assert_not_called()
            get.return_value = httpx.Response(401, request=request)
            assert client.post(route, headers=headers).status_code == 401
            get.return_value = identity(None)
            assert client.post(route, headers=headers).status_code == 403
            get.return_value = identity("24")
            assert client.post(route, headers=headers).status_code == 403
            get.return_value = identity("23")
            result = client.post(route, headers=headers, json={"vps_user_id": "24"})
            assert result.status_code == 200
            assert result.headers["Cache-Control"] == "no-store"
            assert "Set-Cookie" not in result.headers
            get.assert_awaited_with(f"{url}/gtm/api/me", headers={"Cookie": f"salesbot_session={cookie}"})

        token = result.json()["access_token"]
        claims = decode_token(token)
        assert claims["vps_user_id"] == 23
        assert claims["sub"] == "sales"
        assert claims["exp"] - claims["iat"] <= timedelta(minutes=5).total_seconds()
        assert decode_access_token(token) is None

        with patch("app.mcp_five_kit.get_engine", return_value=engine):
            verified = asyncio.run(FiveKitTokenVerifier().verify_token(token))
            assert verified.subject == "sales"
            with Session(engine) as session:
                user = session.get(User, 1)
                user.vps_user_id = 24
                session.add(user)
                session.commit()
            assert asyncio.run(FiveKitTokenVerifier().verify_token(token)) is None
        engine.dispose()
