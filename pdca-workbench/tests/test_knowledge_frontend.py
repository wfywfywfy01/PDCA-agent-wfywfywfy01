"""Offline browser regressions. Build apps/web first; all HTTP is intercepted.

Run: python -B tests/test_knowledge_frontend.py
Uses only synthetic API responses and an isolated Chromium profile.
"""
import base64
import ast
import mimetypes
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT.parent / "apps" / "web" / "dist"
ASSET = "00000000-0000-0000-0000-000000000001"
VERSION = "00000000-0000-0000-0000-000000000002"
EXPORT = "00000000-0000-0000-0000-000000000003"
TITLE = '\" onload="window.__xss=1" data-probe=" <img src=x onerror=window.__xss=1>'
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1kAAAAASUVORK5CYII=")
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'"


class KnowledgeFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path(tempfile.mkdtemp(prefix="pdca-knowledge-ui-"))
        cls.old_temp = {key: os.environ.get(key) for key in ("TEMP", "TMP")}
        os.environ.update(TEMP=str(cls.output), TMP=str(cls.output))
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, args=[
            "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
        ])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        for key, value in cls.old_temp.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        print(f"Offline screenshots: {cls.output}")

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block", accept_downloads=True)
        self.calls = []
        self.context.route("**/*", self.route)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)

    def tearDown(self):
        self.context.close()

    def test_security_policy_preserves_native_form_origin(self):
        tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
        policy = next(node.value.value for node in ast.walk(tree)
                      if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                      and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                              and target.slice.value == "Referrer-Policy" for target in node.targets))
        self.assertEqual(policy, "same-origin")
        captured = []
        def native_form(route):
            request = route.request
            if urlsplit(request.url).netloc != "ui.invalid":
                route.abort()
            elif request.method == "POST":
                captured.append(request.all_headers())
                route.fulfill(status=200, content_type="text/html", body="Submitted")
            else:
                route.fulfill(status=200, content_type="text/html", headers={"Referrer-Policy": policy},
                              body='<form method="post" action="/submitted"><input name="title" value="fixture"><button>Submit</button></form>')
        self.context.unroute("**/*")
        self.context.route("**/*", native_form)
        self.page.goto("https://ui.invalid/form")
        with self.page.expect_navigation():
            self.page.get_by_role("button", name="Submit", exact=True).click()
        self.assertEqual(captured[0].get("origin"), "https://ui.invalid")
        self.assertEqual(captured[0].get("referer"), "https://ui.invalid/form")

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != "ui.invalid":
            route.abort()
            return
        path = url.path
        if path.startswith("/api/"):
            body = request.post_data_json if request.post_data else None
            self.calls.append((path, body, request.headers))
            if path == "/api/auth/me":
                payload = {"username": "test-admin", "role": "admin", "display_name": "Test Admin", "must_change_password": False}
            elif path == "/api/knowledge/scope":
                payload = {"enabled": True, "scope": "all", "can_upload": True, "can_export_original": True,
                           "can_review_sensitive": True, "dealers": [{"store_id": "test", "dealer_id": ASSET, "name": "Test Dealer"}]}
            elif path == "/api/knowledge/search":
                payload = {"items": [{"asset_id": ASSET, "asset_version_id": VERSION, "category": "media",
                                      "sensitivity": "internal", "text": TITLE, "citation": {
                                          "asset_version_id": VERSION, "original_name": "fixture.png", "title": TITLE, "version_number": 1,
                                      }}]}
            elif path.endswith("/content"):
                route.fulfill(status=200, content_type="image/png", body=PNG)
                return
            elif path == "/api/knowledge/reauth":
                if body["password"] != "offline-fixture-password":
                    route.fulfill(status=401, json={"detail": "Password rejected in fixture"})
                    return
                payload = {"ok": True, "expires_in": 300}
            elif path == "/api/knowledge/exports":
                UUID(request.headers["idempotency-key"])
                self.assertEqual(body["confirmation"], "export-original")
                payload = {"export_id": EXPORT, "download_token": "fixture-token-not-real",
                           "download_url": f"/api/knowledge/exports/{EXPORT}/download", "expires_in": 300}
            elif path == f"/api/knowledge/exports/{EXPORT}/download":
                self.assertEqual(body["export_token"], "fixture-token-not-real")
                route.fulfill(status=200, body=b"offline-original", content_type="application/octet-stream",
                              headers={"Content-Disposition": "attachment; filename*=UTF-8''fixture-original.txt"})
                return
            else:
                route.fulfill(status=404, json={"detail": "Offline fixture has no such API"})
                return
            route.fulfill(status=200, json=payload)
            return
        if path == "/legacy":
            route.fulfill(status=200, content_type="text/html", body=(ROOT / "frontend/knowledge_hub.html").read_bytes(),
                          headers={"Content-Security-Policy": CSP})
        elif path == "/knowledge":
            route.fulfill(status=200, content_type="text/html", body=(DIST / "index.html").read_bytes(),
                          headers={"Content-Security-Policy": CSP})
        elif path.startswith("/assets/"):
            file = (DIST / path.lstrip("/")).resolve()
            if file.is_relative_to(DIST.resolve()) and file.is_file():
                route.fulfill(status=200, body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            else:
                route.abort()
        else:
            route.abort()

    def assert_safe_preview(self, selector):
        image = self.page.locator(selector)
        self.assertIn(TITLE, image.get_attribute("alt"))
        self.assertIsNone(image.get_attribute("onload"))
        self.assertIsNone(image.get_attribute("onerror"))
        self.assertFalse(self.page.evaluate("() => Boolean(window.__xss)"))
        self.assertEqual(parse_qs(urlsplit(image.get_attribute("src")).query)["asset_version_id"], [VERSION])
        self.assertTrue(self.page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))

    def test_legacy_safe_render_version_and_export(self):
        for width in (1280, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.page.goto("https://ui.invalid/legacy")
            self.page.locator("#query").fill("test")
            self.page.locator("#search-btn").click()
            self.page.locator("#list img").wait_for()
            self.assert_safe_preview("#list img")
            for href in self.page.locator("#list a").evaluate_all("nodes => nodes.map(n => n.href)"):
                self.assertEqual(parse_qs(urlsplit(href).query)["asset_version_id"], [VERSION])
            self.page.screenshot(path=str(self.output / f"legacy-{width}.png"))
        self.calls.clear()
        self.page.locator("#list [data-export]").click()
        self.page.locator("#export-password").fill("offline-fixture-password")
        self.page.locator("#export-reason").fill("offline original export test")
        with self.page.expect_download() as pending:
            self.page.locator("#export-btn").click()
        self.assertEqual(pending.value.suggested_filename, "fixture-original.txt")
        self.assertEqual([path for path, _, _ in self.calls], [
            "/api/knowledge/reauth", "/api/knowledge/exports", f"/api/knowledge/exports/{EXPORT}/download",
        ])

    def test_vue_safe_render_version_and_export_retry(self):
        self.assertTrue((DIST / "index.html").is_file(), "Build apps/web before running this test")
        self.page.goto("https://ui.invalid/knowledge")
        self.page.locator("#knowledge-query").fill("test")
        self.page.locator(".query-panel button[type=submit]").click()
        self.page.locator(".result img").wait_for()
        for width in (1280, 390):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assert_safe_preview(".result img")
            self.page.screenshot(path=str(self.output / f"vue-{width}.png"))
        self.calls.clear()
        self.page.locator("button.export").click()
        self.page.locator("dialog input[type=password]").fill("wrong-fixture-password")
        self.page.locator("dialog textarea").fill("offline original export test")
        self.page.locator("dialog button[type=submit]").click()
        self.page.locator("dialog [role=alert]").wait_for()
        self.assertEqual([path for path, _, _ in self.calls], ["/api/knowledge/reauth"])
        self.page.locator("dialog input[type=password]").fill("offline-fixture-password")
        self.page.screenshot(path=str(self.output / "vue-export-mobile.png"))
        with self.page.expect_download() as pending:
            self.page.locator("dialog button[type=submit]").click()
        self.assertEqual(pending.value.suggested_filename, "fixture-original.txt")
        self.assertEqual([path for path, _, _ in self.calls], [
            "/api/knowledge/reauth", "/api/knowledge/reauth", "/api/knowledge/exports", f"/api/knowledge/exports/{EXPORT}/download",
        ])
        self.assertEqual(self.page.locator("dialog input[type=password]").input_value(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
