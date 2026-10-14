"""Admin diagnostics distinguish expected login redirects from failed integrations."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.admin.router import _public_knowledge_scope_probe, _upstream_probe


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, **_kwargs):
        self.calls.append((_url, _kwargs))
        return self.response


class AdminDiagnosticsProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_logistics_login_redirect_is_healthy_only_on_local_login_path(self):
        with patch("app.admin.router.httpx.AsyncClient", return_value=_Client(
            httpx.Response(302, headers={"location": "/login?next=/orders"})
        )):
            result = await _upstream_probe("http://logistics.test", "/orders")
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "login_required")
        with patch("app.admin.router.httpx.AsyncClient", return_value=_Client(
            httpx.Response(302, headers={"location": "https://elsewhere.test/login"})
        )):
            result = await _upstream_probe("http://logistics.test", "/orders")
        self.assertFalse(result["ok"])

    async def test_public_scope_requires_enabled_flag(self):
        with patch("app.admin.router.httpx.AsyncClient", return_value=_Client(
            httpx.Response(200, json={"enabled": False})
        )):
            result = await _public_knowledge_scope_probe("test-token")
        self.assertFalse(result["ok"])
        client = _Client(httpx.Response(200, json={"enabled": True}))
        with patch("app.admin.router.httpx.AsyncClient", return_value=client):
            result = await _public_knowledge_scope_probe("test-token")
        self.assertTrue(result["ok"])
        self.assertEqual(client.calls, [(
            "https://pdca-workbench-teams.vertu.cn/api/knowledge/scope",
            {"headers": {"Authorization": "Bearer test-token"}},
        )])
        self.assertEqual(await _public_knowledge_scope_probe(None), {"ok": False, "state": "no_user_token"})
