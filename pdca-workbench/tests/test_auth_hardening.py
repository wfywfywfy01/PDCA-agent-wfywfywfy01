"""Regression coverage for identity, step-up sessions, CSRF and versioned previews.

Run via scripts/test_security_offline.py to block secrets, network and real writes.
"""
import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request

from app.auth.csrf import browser_write_is_trusted
from app.auth.deps import _user_from_proxy_headers, _user_from_vps
from app.auth.models import User
from app.auth.security import (
    KNOWLEDGE_REAUTH_COOKIE, create_access_token, decode_token, hash_password,
    is_token_revoked, revoke_token,
)
from app.auth.vps_identity import ensure_vps_user
from app.database import get_session
from app.knowledge.mcp import PDCATokenVerifier
from app.main import app


class AuthHardeningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            auth_mode="local", portal_mode="workbench", trust_proxy_headers=False,
            trusted_proxy_ips={"127.0.0.1"}, trust_proxy_role_header=False,
            secure_cookies=True, secret_key="isolated-regression-key-not-a-real-secret",
            algorithm="HS256", access_token_expire_minutes=60,
            workbench_base_url="https://testserver/", frame_ancestors=["https://parent.invalid"],
            acquisition_frame_origin="", knowledge_hub_enabled=True,
            knowledge_hub_team_map={},
        )
        self.stack = ExitStack()
        for module in ("main", "auth.csrf", "auth.deps", "auth.security", "auth.router", "auth.vps_identity", "knowledge.router"):
            self.stack.enter_context(patch(f"app.{module}.get_settings", return_value=self.settings))
        for module in ("database", "audit", "knowledge.mcp"):
            self.stack.enter_context(patch(f"app.{module}.get_engine", return_value=self.engine))
        with Session(self.engine) as session:
            session.add_all([
                User(username="admin-test", role="admin", data_scope="all", must_change_password=False,
                     hashed_password=hash_password("only-for-offline-tests")),
                User(username="target-test", role="viewer", must_change_password=False, hashed_password="x"),
            ])
            session.commit()

        def local_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = local_session
        self.client = TestClient(app, base_url="https://testserver", follow_redirects=False)
        self.origin = {"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.stack.close()
        self.engine.dispose()

    def login(self):
        response = self.client.post("/api/auth/login", headers=self.origin, json={
            "username": "admin-test", "password": "only-for-offline-tests",
        })
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def step_up(self):
        response = self.client.post("/api/knowledge/reauth", headers=self.origin,
                                    json={"password": "only-for-offline-tests"})
        self.assertEqual(response.status_code, 200)
        return response.cookies[KNOWLEDGE_REAUTH_COOKIE]

    def export(self):
        return self.client.post("/api/knowledge/exports", headers={**self.origin, "Idempotency-Key": "offline-export-test"},
                                json={"asset_id": str(uuid4()), "reason": "offline export verification", "confirmation": "export-original"})

    def test_all_sso_entries_reject_inactive_user_without_mutation(self):
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == "target-test")).one()
            user.is_active = False
            session.add(user)
            session.commit()
            identity = {"login": user.username, "name": "SSO changed name", "uid": 1}
            with self.assertRaises(HTTPException):
                ensure_vps_user(session, identity)
            request = Request({"type": "http", "method": "GET", "path": "/", "headers":
                               [(b"x-vps-user-login", b"target-test")], "client": ("127.0.0.1", 1)})
            self.settings.trust_proxy_headers = True
            with self.assertRaises(HTTPException):
                asyncio.run(_user_from_proxy_headers(session, request))
            with patch("app.auth.deps.fetch_vps_me_payload", return_value=identity), self.assertRaises(HTTPException):
                asyncio.run(_user_from_vps(session, request))
            with patch("app.auth.router.resolve_odoo_sso_secret", return_value="test-only"), patch(
                "app.auth.router.parse_odoo_ticket", return_value=identity
            ):
                self.assertEqual(self.client.get("/api/auth/odoo-sso?ticket=test").status_code, 403)
            with patch("app.auth.router.identity_from_odoo_session", return_value=identity):
                self.assertEqual(self.client.get("/walkin-submit?session_id=test").status_code, 403)
            session.refresh(user)
            self.assertFalse(user.is_active)
            self.assertEqual(user.display_name, "")

    def test_deactivation_rotates_version_and_reenable_does_not_restore_old_jwt(self):
        self.login()
        for method in ("patch", "delete"):
            with self.subTest(method=method):
                with Session(self.engine) as session:
                    user = session.exec(select(User).where(User.username == "target-test")).one()
                    before = user.pwd_version
                    old = create_access_token({"sub": user.username, "pwd_v": before})
                kwargs = {"json": {"is_active": False}} if method == "patch" else {}
                response = self.client.request(method, "/api/admin/users/target-test", headers=self.origin, **kwargs)
                self.assertEqual(response.status_code, 200)
                with Session(self.engine) as session:
                    user = session.exec(select(User).where(User.username == "target-test")).one()
                    self.assertEqual(user.pwd_version, before + 1)
                self.assertEqual(self.client.patch("/api/admin/users/target-test", headers=self.origin,
                                                  json={"is_active": True}).status_code, 200)
                self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code, 401)

    def test_special_purpose_tokens_are_rejected_by_http_and_mcp(self):
        for purpose in ("knowledge-original-export", "future-purpose", None):
            with self.subTest(purpose=purpose):
                token = create_access_token({"sub": "admin-test", "pwd_v": 0, "purpose": purpose})
                self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)
                self.assertIsNone(asyncio.run(PDCATokenVerifier().verify_token(token)))

    def test_logout_revokes_cookie_bearer_and_stepup_and_clears_cookies(self):
        primary = self.login()
        stepup = self.step_up()
        other = create_access_token({"sub": "admin-test", "pwd_v": 0})
        response = self.client.post("/api/auth/logout", headers={**self.origin, "Authorization": f"Bearer {other}"})
        self.assertEqual(response.status_code, 200)
        for token in (primary, stepup, other):
            self.assertTrue(is_token_revoked(decode_token(token)))
        self.assertNotIn("pdca_token", self.client.cookies)
        self.assertNotIn(KNOWLEDGE_REAUTH_COOKIE, self.client.cookies)
        self.assertEqual(len(response.headers.get_list("set-cookie")), 2)

    def test_reauth_is_bound_to_login_and_revocation_is_enforced(self):
        primary = self.login()
        with patch("app.knowledge.router.request_json", new=AsyncMock(return_value={
            "export_id": str(uuid4()), "download_token": "x" * 43, "expires_at": "test", "expires_in": 300,
        })) as upstream:
            self.assertEqual(self.export().status_code, 403)
            stepup = self.step_up()
            self.assertEqual(decode_token(stepup)["login_jti"], decode_token(primary)["jti"])
            self.assertEqual(self.export().status_code, 200)
            upstream.reset_mock()
            self.login()
            self.assertEqual(self.export().status_code, 403)
            stepup = self.step_up()
            revoke_token(stepup)
            self.assertEqual(self.export().status_code, 403)
            upstream.assert_not_awaited()

    def test_reauth_requires_an_active_login_token(self):
        token = self.login()
        revoke_token(token)
        response = self.client.post("/api/knowledge/reauth", headers=self.origin,
                                    json={"password": "only-for-offline-tests"})
        self.assertEqual(response.status_code, 401)

    def test_csrf_sources_and_no_forged_bearer_bypass(self):
        self.login()
        path = "/api/admin/users/target-test/require-password-change"
        for headers in ({}, {"Origin": "https://evil.invalid"}, {"Origin": "null"},
                        {"Authorization": "Bearer forged"}, {"Origin": "https://testserver.evil.invalid"},
                        {"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post(path, headers=headers).status_code, 403)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(User).where(User.username == "target-test")).one().pwd_version, 0)
        self.assertEqual(self.client.post(path, headers=self.origin).status_code, 200)
        self.assertEqual(self.client.post(path, headers={"Referer": "https://testserver/app/knowledge"}).status_code, 200)

    def test_bearer_cli_works_without_browser_headers_or_cookies(self):
        token = self.login()
        self.client.cookies.clear()
        response = self.client.post("/api/admin/users/target-test/require-password-change",
                                    headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)

    def test_form_and_fetch_metadata_rules_include_tls_termination(self):
        def trusted(headers, method="POST", scheme="https"):
            request = Request({"type": "http", "method": method, "scheme": scheme, "server": ("testserver", 80),
                               "path": "/questionnaire", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})
            return browser_write_is_trusted(request)
        for content_type in ("application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain"):
            with self.subTest(content_type=content_type):
                self.assertFalse(trusted({"Content-Type": content_type}))
                self.assertTrue(trusted({"Content-Type": content_type, "Origin": "https://testserver"}))
        self.assertTrue(trusted({"Host": "testserver", "Origin": "https://testserver", "Sec-Fetch-Site": "same-origin",
                                 "Cookie": "pdca_token=fixture"}, scheme="http"))
        self.assertFalse(trusted({"Cookie": "pdca_token=fixture", "Origin": "https://parent.invalid"}))
        self.assertFalse(trusted({"Cookie": "pdca_token=fixture", "Origin": "null", "Referer": "https://testserver/"}))
        self.assertFalse(trusted({"Cookie": "pdca_token=fixture", "X-Forwarded-Host": "evil.invalid", "Origin": "https://evil.invalid"}))
        self.assertTrue(trusted({}, method="GET"))

    def test_preview_forwards_validated_version_and_rejects_invalid_uuid(self):
        self.login()
        asset_id, version_id = uuid4(), uuid4()
        from fastapi.responses import Response
        with patch("app.knowledge.router.request_content", new=AsyncMock(return_value=Response(b"preview"))) as upstream:
            path = f"/api/knowledge/assets/{asset_id}/content"
            self.assertEqual(self.client.get(f"{path}?asset_version_id={version_id}").status_code, 200)
            self.assertEqual(upstream.await_args.args[:2], ("GET", f"/v1/assets/{asset_id}/content?asset_version_id={version_id}"))
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(upstream.await_args.args[1], f"/v1/assets/{asset_id}/content")
            upstream.reset_mock()
            self.assertEqual(self.client.get(f"{path}?asset_version_id=invalid").status_code, 422)
            upstream.assert_not_awaited()
