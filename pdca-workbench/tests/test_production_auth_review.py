"""Regression checks for production identity boundaries; all data is isolated."""
from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth import router as auth_router
from app.auth.models import User
from app.auth.odoo_sso import issue_odoo_ticket, parse_odoo_ticket
from app.auth.scope import resolve_data_scope
from app.auth.security import create_access_token
from app.auth.security_state import LoginFailRecord
from app.auth.vps_identity import ensure_vps_user
from app.database import get_session
from app.knowledge.mcp import PDCATokenVerifier


class ProductionAuthReviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            auth_mode="local", portal_mode="workbench", trust_proxy_headers=False,
            trusted_proxy_ips=set(), secure_cookies=False, access_token_expire_minutes=60,
            secret_key="test-only-auth-review-secret-32-characters", algorithm="HS256",
        )
        self.patches = ExitStack()
        for module in ("deps", "router", "security"):
            self.patches.enter_context(patch(f"app.auth.{module}.get_settings", return_value=self.settings))
        self.patches.enter_context(patch("app.database.get_engine", return_value=self.engine))
        self.patches.enter_context(patch("app.knowledge.mcp.get_engine", return_value=self.engine))
        self.patches.enter_context(patch("app.auth.router.log_action"))
        self.patches.enter_context(patch("app.auth.vps_identity._sync_role_enabled", return_value=False))
        self.patches.enter_context(patch("app.auth.router.resolve_odoo_sso_secret", return_value="test-sso-secret"))
        app = FastAPI()
        app.include_router(auth_router.router)

        def session_dependency():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = session_dependency
        self.client = TestClient(app)
        auth_router._fail_log.clear()
        with Session(self.engine) as session:
            session.add(User(
                username="employee", hashed_password="unused", role="sales",
                data_scope="self", must_change_password=False,
            ))
            session.commit()

    def tearDown(self):
        self.client.close()
        self.patches.close()
        auth_router._fail_log.clear()
        self.engine.dispose()

    def test_odoo_sso_cannot_reactivate_disabled_account(self):
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == "employee")).one()
            user.is_active = False
            session.add(user)
            session.commit()
        ticket = issue_odoo_ticket(login="employee", uid=123, name="Employee", secret="test-sso-secret")
        response = self.client.get("/api/auth/odoo-sso", params={"ticket": ticket}, follow_redirects=False)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("pdca_token", response.cookies)
        with Session(self.engine) as session:
            self.assertFalse(session.exec(select(User).where(User.username == "employee")).one().is_active)

    def test_odoo_login_cookie_authenticates_followup_in_vps_mode(self):
        self.settings.auth_mode = "vps"
        ticket = issue_odoo_ticket(login="employee", uid=123, name="Employee", secret="test-sso-secret")
        response = self.client.get("/api/auth/odoo-sso", params={"ticket": ticket}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        token = response.cookies["pdca_token"]
        # Secure iframe cookies are sent by HTTPS clients; bearer exercises the same JWT path.
        following = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(following.status_code, 200)
        self.assertEqual(following.json()["username"], "employee")
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "employee", "password": "unused"}).status_code, 403)

    def test_sso_display_name_does_not_grant_owner_data_scope(self):
        for login in ("new-sales", "employee"):
            with self.subTest(login=login), Session(self.engine) as session:
                user = ensure_vps_user(session, {
                    "login": login, "name": "Another Salesperson", "job_title": "销售",
                })
                self.assertEqual(resolve_data_scope(user, session).owner_keys, ())

    def test_reauth_token_is_not_a_login_or_mcp_credential(self):
        token = create_access_token({"sub": "employee", "pwd_v": 0, "purpose": "knowledge-original-export"})
        response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(asyncio.run(PDCATokenVerifier().verify_token(token)))

    def test_rate_limit_counts_each_attempt_once_and_keeps_full_lockout(self):
        key = "test-ip:employee"
        for timestamp in (1000, 1001, 1002, 1003):
            with patch("app.auth.router.time.time", return_value=timestamp):
                auth_router._record_fail(key)
                auth_router._check_rate_limit(key)
        with patch("app.auth.router.time.time", return_value=1004):
            auth_router._record_fail(key)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(LoginFailRecord)).all()), 5)
        # A different worker has no in-memory failures but must see the shared lock.
        auth_router._fail_log.clear()
        with patch("app.auth.router.time.time", return_value=1400), self.assertRaises(HTTPException) as blocked:
            auth_router._check_rate_limit(key)
        self.assertEqual(blocked.exception.status_code, 429)
        with patch("app.auth.router.time.time", return_value=1905):
            auth_router._check_rate_limit(key)

    def test_slow_failures_outside_five_minute_window_do_not_lock(self):
        key = "test-ip:slow"
        for timestamp in (1000, 1310, 1620, 1930, 2240):
            with patch("app.auth.router.time.time", return_value=timestamp):
                auth_router._record_fail(key)
                auth_router._check_rate_limit(key)

    def test_success_in_another_worker_clears_shared_failures(self):
        key = "test-ip:reset"
        for timestamp in (1000, 1001, 1002, 1003, 1004):
            with patch("app.auth.router.time.time", return_value=timestamp):
                auth_router._record_fail(key)
        # The other worker cannot clear this worker's memory cache.
        auth_router._db_clear_fail(key)
        with patch("app.auth.router.time.time", return_value=1010):
            auth_router._check_rate_limit(key)

    def test_malformed_unicode_sso_ticket_fails_closed(self):
        for ticket in ("你好.abc", "abc.你好"):
            with self.subTest(ticket=ticket):
                self.assertIsNone(parse_odoo_ticket(ticket, "test-sso-secret"))

    def test_sso_redirect_cannot_escape_origin_with_backslash(self):
        self.assertEqual(auth_router._safe_next_path("/\\untrusted.example/path"), "/")
        self.assertEqual(auth_router._safe_next_path("/app/knowledge?category=contract"), "/app/knowledge?category=contract")


if __name__ == "__main__":
    unittest.main()
