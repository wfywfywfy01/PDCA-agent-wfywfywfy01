"""Offline runtime diagnostics UI: synthetic fixtures, no external requests."""
import mimetypes
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

DIST = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"


@unittest.skipUnless((DIST / "index.html").is_file(), "Build apps/web before browser tests")
class RuntimeFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block", viewport={"width": 320, "height": 900})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.unknown = False
        self.context.route("**/*", self.route)

    def tearDown(self):
        self.context.close()

    def route(self, route):
        url = urlsplit(route.request.url)
        if url.netloc != "ui.invalid" or route.request.method != "GET":
            route.abort()
            return
        path = url.path
        if path == "/api/auth/me":
            route.fulfill(json={"username": "qa-admin", "role": "admin", "must_change_password": False})
        elif path == "/api/admin/diagnostics":
            route.fulfill(json={
                "modules": {}, "database": {"connected": True, "mode": "fixture"},
                "legacy_bridge_probe": {"ok": True}, "vertu_cli_probe": {"ok": False, "detail": "认证失败"},
                "runtime": {
                    "disk": {"ok": False, "state": "unknown" if self.unknown else "warning",
                             "free_percent": None if self.unknown else 14.2, "free_bytes": None if self.unknown else 8*1024**3},
                    "jobs": {"ok": False, "state": "unknown" if self.unknown else "available",
                             "failed_count": None if self.unknown else 1, "stale_count": None if self.unknown else 0,
                             "items": [] if self.unknown else [{"job_name": "todo_ledger_sync", "status": "failed", "failed": True,
                                "stale": False, "started_at": "2026-10-19T10:10:00Z", "last_success_at": None}]},
                },
            })
        elif path.startswith("/api/"):
            route.fulfill(status=404, json={"detail": "Unknown fixture API"})
        elif path.startswith("/app/assets/"):
            file = (DIST / path.removeprefix("/app/")).resolve()
            if file.is_relative_to(DIST.resolve()) and file.is_file():
                route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            else:
                route.abort()
        elif path == "/app/admin/sync":
            route.fulfill(content_type="text/html", body=(DIST / "index.html").read_bytes())
        else:
            route.abort()

    def test_failures_disk_warning_and_real_cli_state_at_all_breakpoints(self):
        self.page.goto("https://ui.invalid/app/admin/sync")
        expect(self.page.get_by_role("heading", name="后台任务最近运行")).to_be_visible()
        expect(self.page.get_by_text("可用 14.2%", exact=True)).to_be_visible()
        cli = self.page.get_by_role("row").filter(has=self.page.get_by_text("vertu-cli 凭据", exact=True))
        expect(cli).to_contain_text("不可用")
        expect(cli).to_contain_text("认证失败")
        for width in (320, 768, 1024, 1440):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.page.wait_for_function("document.documentElement.scrollWidth <= innerWidth + 2", timeout=2000)
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 2"), f"width={width}")
        self.page.get_by_role("button", name="刷新自检").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.tagName"), "BUTTON")
        self.assertEqual(self.errors, [])

    def test_unknown_states_do_not_show_zero_failures(self):
        self.unknown = True
        self.page.goto("https://ui.invalid/app/admin/sync")
        expect(self.page.get_by_text("任务状态未获取，不按零故障展示", exact=True)).to_be_visible()
        expect(self.page.get_by_text("磁盘余量读取失败", exact=True)).to_be_visible()
        expect(self.page.get_by_text("最近失败 0 项", exact=False)).to_have_count(0)
