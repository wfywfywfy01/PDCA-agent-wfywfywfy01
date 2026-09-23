# -*- coding: utf-8 -*-
"""物流运营台同源代理的路径、角色和响应重写测试。"""
from __future__ import annotations

import os
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.auth.models import User
from app.config import Settings
from app.logistics.admin_proxy import (
    _check_role,
    _rewrite_html,
    _rewrite_location,
    _rewrite_set_cookie,
    _request_headers,
    _target_path,
)
from app.main import app


class LogisticsAdminProxyTests(unittest.TestCase):
    def test_rewrites_root_links_and_adds_return_link(self):
        source = ("<nav><a href='/orders'>订单</a></nav>"
                  "<link rel='stylesheet' href='/admin.css'>"
                  "<script src='/admin.js'></script>").encode()
        result = _rewrite_html(source, "text/html; charset=utf-8").decode()
        self.assertIn("href='/logistics-admin/orders'", result)
        self.assertIn("src='/logistics-admin/admin.js'", result)
        self.assertIn("href='/logistics-admin/admin.css'", result)
        self.assertIn('href="/app/logistics"', result)

    def test_non_html_is_untouched(self):
        source = b'{"href":"/orders"}'
        self.assertEqual(_rewrite_html(source, "application/json"), source)

    def test_rewrites_redirect_and_cookie_paths(self):
        self.assertEqual(_rewrite_location("/orders"), "/logistics-admin/orders")
        self.assertEqual(_rewrite_location("https://example.test/orders"), "https://example.test/orders")
        self.assertIn("Path=/logistics-admin/login", _rewrite_set_cookie("x=1; Path=/login; HttpOnly"))
        self.assertIn("Path=/logistics-admin", _rewrite_set_cookie("x=1; Path=/; HttpOnly"))

    def test_target_path_rejects_traversal(self):
        with self.assertRaises(HTTPException):
            _target_path("orders/../users")
        self.assertEqual(_target_path(""), "/")

    def test_proxy_forwards_only_logistics_cookies(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/logistics-admin/orders",
            "raw_path": b"/logistics-admin/orders",
            "query_string": b"",
            "headers": [(b"cookie", b"pdca_token=secret; logistics_session=ok; other=x")],
            "client": ("127.0.0.1", 1),
            "server": ("pdca.test", 443),
            "scheme": "https",
        }
        headers = _request_headers(Request(scope), "http://logistics-track:8080")
        self.assertEqual(headers.get("Cookie"), "logistics_session=ok")
        self.assertNotIn("pdca_token", headers.get("Cookie", ""))

    def test_role_gate_allows_read_and_restricts_writes(self):
        _check_role(User(role="viewer"), "/orders", "GET")
        _check_role(User(role="admin"), "/users", "GET")
        with self.assertRaises(HTTPException):
            _check_role(User(role="viewer"), "/api/orders/1/packages", "POST")
        with self.assertRaises(HTTPException):
            _check_role(User(role="manager"), "/users", "GET")
        with self.assertRaises(HTTPException):
            _check_role(User(role="dealer"), "/orders", "GET")

    def test_route_is_registered(self):
        self.assertIn("/logistics-admin/{path:path}", {route.path for route in app.routes})

    def test_settings_accept_only_explicit_origin_without_userinfo_or_query(self):
        with patch.dict(
            os.environ,
            {"PDCA_LOGISTICS_ADMIN_UPSTREAM": "http://logistics-track:8080"},
            clear=False,
        ):
            settings = Settings()
        self.assertEqual(settings.logistics_admin_upstream, "http://logistics-track:8080")

        with patch.dict(
            os.environ,
            {"PDCA_LOGISTICS_ADMIN_UPSTREAM": "http://user:pass@logistics-track:8080/?x=1"},
            clear=False,
        ):
            rejected = Settings()
        self.assertEqual(rejected.logistics_admin_upstream, "")

    def test_production_deploy_defaults_to_private_logistics_network(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        deploy = (root / "scripts" / "deploy_remote_docker.ps1").read_text(encoding="utf-8")

        self.assertIn(
            "PDCA_LOGISTICS_ADMIN_UPSTREAM: ${PDCA_LOGISTICS_ADMIN_UPSTREAM:-http://logistics-track:8080}",
            compose,
        )
        self.assertIn("name: dealer-knowledge", compose)
        self.assertIn('$logisticsAdminUpstream = "http://logistics-track:8080"', deploy)
        self.assertIn('"-e", "PDCA_LOGISTICS_ADMIN_UPSTREAM=$logisticsAdminUpstream"', deploy)

    def test_proxy_forwards_html_with_same_origin_rewrites(self):
        from app.logistics import admin_proxy

        class FakeClient:
            def __init__(self, **_kwargs):
                self.request = None

            def build_request(self, method, url, **kwargs):
                self.request = (method, url, kwargs)
                return object()

            async def send(self, _request, stream=False):
                self.response = __import__("httpx").Response(
                    303,
                    headers={
                        "content-type": "text/html; charset=utf-8",
                        "location": "/orders",
                        "set-cookie": "logistics_login_csrf=x; Path=/login; HttpOnly",
                        "x-frame-options": "DENY",
                    },
                    content=b"<nav><a href='/orders'>orders</a></nav>",
                )
                return self.response

            async def aclose(self):
                return None

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/logistics-admin/orders",
            "raw_path": b"/logistics-admin/orders",
            "query_string": b"q=test",
            "headers": [(b"accept", b"text/html")],
            "client": ("127.0.0.1", 1),
            "server": ("pdca.test", 443),
            "scheme": "https",
        }
        request = Request(scope)
        settings = SimpleNamespace(
            logistics_admin_upstream="http://logistics-track:8080",
            logistics_admin_timeout_seconds=3,
        )
        with patch.object(admin_proxy.httpx, "AsyncClient", FakeClient), patch.object(
            admin_proxy, "get_settings", return_value=settings
        ):
            response = asyncio.run(
                admin_proxy.proxy_logistics_admin("orders", request, User(role="admin"))
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/logistics-admin/orders")
        self.assertEqual(response.headers["x-frame-options"], "SAMEORIGIN")
        self.assertIn("/logistics-admin/orders", response.body.decode())
        self.assertIn("Path=/logistics-admin/login", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
