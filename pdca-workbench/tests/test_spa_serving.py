# -*- coding: utf-8 -*-
"""P1：SPA 托管（/app）冒烟测试。

dist 缺失时（CI 单测环境未构建前端）整体跳过；docker 冒烟或本地构建后
自动启用。覆盖：入口页、客户端路由回退、静态资源内容类型。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPA_DIST = _REPO_ROOT / "apps" / "web" / "dist"


def _settings(temp_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        auth_mode="local",
        trust_proxy_headers=False,
        secure_cookies=False,
        portal_mode="walkin",
        trusted_proxy_ips=set(),
        trust_proxy_role_header=False,
        allow_sqlite_fallback=False,
        access_token_expire_minutes=60,
        secret_key="test-secret-key-that-is-long-enough-for-jwt",
        algorithm="HS256",
        vps_login_url="https://example.invalid",
        max_reported_revenue_usd=5_000_000,
        revenue_review_threshold_usd=1_000_000,
        repo_root=_REPO_ROOT,
        scripts_dir=_REPO_ROOT / "data_platform" / "data_role_pdca_mvp" / "scripts",
        vertu_command="vertu-cli",
        environment="development",
        scheduler_enabled=False,
        require_vertu=False,
        host="127.0.0.1",
        port=8767,
        mvp_root=_REPO_ROOT / "data_platform" / "data_role_pdca_mvp",
        data_dir=temp_dir,
        spa_dist_dir=_SPA_DIST,
    )


@unittest.skipUnless((_SPA_DIST / "index.html").is_file(), "SPA dist 未构建，跳过")
class SpaServingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'.replace('/', '_')}"
        )
        SQLModel.metadata.create_all(self.engine)
        settings = _settings(Path(self.temp_dir.name))
        self.patches = [
            patch("app.main.get_settings", return_value=settings),
            patch("app.auth.deps.get_settings", return_value=settings),
            patch("app.auth.router.get_settings", return_value=settings),
            patch("app.auth.security.get_settings", return_value=settings),
            patch("app.legacy.bridge.get_settings", return_value=settings),
            patch("app.spa.router.get_settings", return_value=settings),
        ]
        for item in self.patches:
            item.start()

        def override_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        self.engine.dispose()
        for item in self.patches:
            item.stop()
        app.dependency_overrides.clear()
        self.temp_dir.cleanup()

    def test_entry_serves_index_html(self):
        res = self.client.get("/app")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])

    def test_client_route_falls_back_to_index(self):
        res = self.client.get("/app/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])

    def test_asset_serves_with_correct_content_type(self):
        css_files = sorted((_SPA_DIST / "assets").glob("*.css"))
        if not css_files:
            self.skipTest("dist 无 css 资源")
        res = self.client.get(f"/app/assets/{css_files[0].name}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/css", res.headers["content-type"])

    def test_missing_asset_falls_back_to_index_not_redirect(self):
        # /app/* 必须公开托管，鉴权中间件不得重定向到 /login
        res = self.client.get("/app/assets/not-exists-xyz.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
