"""Offline browser checks for the homepage authentication gate; all data is synthetic."""
from __future__ import annotations

import mimetypes
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


DIST = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
BUSINESS_PATHS = {
    "/api/dashboard/sell-in", "/api/dashboard/sell-out",
    "/api/workbench/today", "/api/customer-center/summary",
}


@unittest.skipUnless((DIST / "index.html").is_file(), "Build apps/web before browser tests")
class HomeAuthFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.page = self.context.new_page()
        self.mode = "anonymous"
        self.calls = []
        self.context.route("**/*", self.route)

    def tearDown(self):
        self.context.close()

    def route(self, route):
        url = urlsplit(route.request.url)
        if url.netloc != "ui.invalid":
            route.abort()
            return
        path = url.path
        if path.startswith("/api/"):
            self.calls.append(path)
            if path == "/api/auth/me":
                if self.mode == "anonymous":
                    route.fulfill(status=401, json={"detail": "未登录"})
                else:
                    route.fulfill(json={"username": "qa-viewer", "display_name": "QA Viewer",
                                        "role": "viewer", "must_change_password": self.mode == "change"})
            elif path == "/api/auth/config":
                route.fulfill(json={"auth_mode": "local"})
            elif path in BUSINESS_PATHS:
                payload = {"amount": 100, "wan": 0.01, "note": "QA", "state": "live"}
                if path == "/api/workbench/today":
                    payload = {"date": "2026-10-14", "facts": {}, "actions": [],
                               "closure": {"reported": 0, "expected": 0, "complete": True,
                                           "report_date": "2026-10-13"}}
                elif path == "/api/customer-center/summary":
                    payload = []
                route.fulfill(json=payload)
            else:
                route.fulfill(status=404, json={"detail": "Unknown fixture API"})
            return
        if path in {"/app/", "/app/login"}:
            route.fulfill(content_type="text/html", body=(DIST / "index.html").read_bytes())
        elif path.startswith("/app/assets/"):
            file = (DIST / path.removeprefix("/app/")).resolve()
            if file.is_relative_to(DIST.resolve()) and file.is_file():
                route.fulfill(body=file.read_bytes(),
                              content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            else:
                route.abort()
        else:
            route.abort()

    def test_anonymous_home_requests_only_identity(self):
        self.page.goto("https://ui.invalid/app/")
        expect(self.page).to_have_url("https://ui.invalid/app/login?next=/")
        self.assertEqual(self.calls.count("/api/auth/me"), 1)
        self.assertFalse(BUSINESS_PATHS.intersection(self.calls))

    def test_password_change_home_does_not_fetch_business_data(self):
        self.mode = "change"
        self.page.goto("https://ui.invalid/app/")
        expect(self.page).to_have_url("https://ui.invalid/app/login?change_password=1&next=/")
        self.assertEqual(parse_qs(urlsplit(self.page.url).query).get("change_password"), ["1"])
        self.assertFalse(BUSINESS_PATHS.intersection(self.calls))

    def test_authenticated_home_loads_business_sections(self):
        self.mode = "authenticated"
        self.page.goto("https://ui.invalid/app/")
        expect(self.page.get_by_role("heading", name="经营驾驶舱")).to_be_visible()
        expect(self.page.get_by_text("QA Viewer").first).to_be_visible()
        self.assertEqual(BUSINESS_PATHS.intersection(self.calls), BUSINESS_PATHS)


if __name__ == "__main__":
    unittest.main()
