"""Offline regression for snapshot-first/live-later Sell-in rendering."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import os
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit


class DashboardStatic(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.path = urlsplit(self.path).path.removeprefix('/app')
        if not Path(self.path).suffix:
            self.path = '/index.html'
        super().do_GET()


class DashboardUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_sell_in_does_not_flash_overview_snapshot(self):
        from playwright.async_api import async_playwright, expect

        build = Path(__file__).resolve().parents[2] / 'apps/web/dist'
        if not (build / 'index.html').is_file():
            self.skipTest('Build apps/web before running the offline browser regression')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(DashboardStatic, directory=str(build)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        evidence = os.environ.get('PDCA_UI_EVIDENCE_DIR')
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    for width in (320, 768, 1024, 1440):
                        with self.subTest(width=width):
                            context = await browser.new_context(
                                viewport={'width': width, 'height': 900}, timezone_id='Asia/Shanghai')
                            page = await context.new_page()
                            errors, console_messages, unexpected = [], [], []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.on('console', lambda message: console_messages.append(message.text)
                                    if message.type in {'error', 'warning'} else None)
                            release = asyncio.Event()
                            overview_sent = asyncio.Event()

                            async def api(route):
                                path = urlsplit(route.request.url).path
                                self.assertEqual(route.request.method, 'GET', 'No business writes in this test')
                                payloads = {
                                    '/api/auth/me': {'username': 'synthetic-admin', 'display_name': '验收账号', 'role': 'admin'},
                                    '/api/omega/status': {'ready': False},
                                    '/api/duzhan-agents': [],
                                    '/api/dashboard/overview': {
                                        'sellInWan': 1189, 'sellInSub': 'synthetic DB snapshot',
                                        'dataState': {'sellIn': 'live'},
                                        'dataSource': {'sellIn': 'synthetic-snapshot'},
                                        'dataAsOf': '2026-10-23T06:00:00+08:00'},
                                    '/api/dashboard/sell-out': {'amount': 0, 'wan': 0, 'state': 'live', 'note': '合成终销'},
                                    '/api/customer-center/summary': [],
                                    '/api/task-center/summary': [],
                                    '/api/task-center/panel': {'items': [], 'summary': []},
                                    '/api/dealer/sellin-summary': {'month': '2026-10', 'total_wan': 0,
                                        'dealers': [], 'has_data': False, 'trend': []},
                                }
                                if path == '/api/dashboard/sell-in':
                                    await release.wait()
                                    payload = {'amount': 11663200, 'wan': 1166.32, 'state': 'live',
                                        'note': 'synthetic live KPI', 'source': 'synthetic-live',
                                        'as_of': '2026-10-23T11:00:00+08:00'}
                                else:
                                    if path not in payloads:
                                        unexpected.append(path)
                                    payload = payloads.get(path, {})
                                await route.fulfill(status=200, json=payload)
                                if path == '/api/dashboard/overview':
                                    overview_sent.set()

                            await page.route('**/api/**', api)
                            await page.route('**/favicon.ico', lambda route: route.fulfill(status=204))
                            try:
                                await page.goto(base + '/app/dashboard', wait_until='domcontentloaded')
                                await asyncio.wait_for(overview_sent.wait(), timeout=10)
                                card = page.locator('.compare-card').first
                                await expect(card).to_be_visible()
                                # Let the completed overview response and Vue render flush while KPI stays blocked.
                                await page.wait_for_timeout(150)
                                await expect(card.locator('.compare-value')).to_have_text('…')
                                await expect(card).not_to_contain_text('1,189.00')
                                await expect(card).not_to_contain_text('实时接口无数据')
                                await expect(card.locator('.compare-note')).to_contain_text('加载')
                                if evidence:
                                    await page.screenshot(path=str(Path(evidence) / f'pending-{width}.png'))
                                release.set()
                                await expect(card.locator('.compare-value')).to_have_text('1,166.32 万 CNY')
                                await expect(card.locator('.compare-meta')).to_contain_text('synthetic-live')
                                await expect(card.locator('.compare-meta')).not_to_contain_text('synthetic-snapshot')
                                kpi = page.locator('.stats .stat').first
                                await expect(kpi.locator('.stat-value')).to_have_text('1,166.32 万 CNY')
                                self.assertFalse(await page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                                self.assertEqual(errors, [])
                                self.assertEqual(console_messages, [])
                                self.assertEqual(unexpected, [])
                                if evidence:
                                    await page.screenshot(path=str(Path(evidence) / f'ready-{width}.png'))
                            finally:
                                release.set()
                                await context.close()
                finally:
                    await browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
