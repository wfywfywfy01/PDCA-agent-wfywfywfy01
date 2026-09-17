# -*- coding: utf-8 -*-
"""Vemory 全量拉取 API 单元测试：列表分页 / 详情缓存 / 音频直链缓存。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.meeting import vemory as v


def _list_payload(rows, total, ok=True):
    return {"ok": ok, "total": total, "meetings": rows}


def _row(idx):
    return {
        "id": f"m{idx}",
        "name": f"会议{idx}",
        "start_time": f"2026-09-0{idx % 9 + 1}T01:23:40Z",
        "owner_name": "王宇彤",
        "owner_user_id": 14344,
        "template_type": "会议纪要",
        "duration_seconds": 600,
        "source": "vemory",
    }


class VemoryListTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        v.clear_cache()

    async def test_list_paginates_until_total(self):
        pages = {
            1: _list_payload([_row(i) for i in range(50)], 120),
            2: _list_payload([_row(i) for i in range(50, 100)], 120),
            3: _list_payload([_row(i) for i in range(100, 120)], 120),
        }

        async def fake(args, timeout=45.0):
            return pages[int(args[args.index("--page") + 1])]

        with patch("app.meeting.vemory.run_vertu_json", new=AsyncMock(side_effect=fake)):
            rows, error = await v.list_dealer_meetings("2026-09-01", "2026-09-30")
        self.assertIsNone(error)
        self.assertEqual(len(rows), 120)
        self.assertEqual(rows[0]["date"], "2026-09-01")

    async def test_list_stops_on_short_page(self):
        calls = []

        async def fake(args, timeout=45.0):
            calls.append(int(args[args.index("--page") + 1]))
            return _list_payload([_row(i) for i in range(30)], 30)

        with patch("app.meeting.vemory.run_vertu_json", new=AsyncMock(side_effect=fake)):
            rows, error = await v.list_dealer_meetings("2026-09-01", "2026-09-30")
        self.assertIsNone(error)
        self.assertEqual(len(rows), 30)
        self.assertEqual(calls, [1])

    async def test_list_returns_error_when_not_ok(self):
        async def fake(args, timeout=45.0):
            return {"ok": False, "total": 0, "meetings": []}

        with patch("app.meeting.vemory.run_vertu_json", new=AsyncMock(side_effect=fake)):
            rows, error = await v.list_dealer_meetings("2026-09-01", "2026-09-30")
        self.assertEqual(rows, [])
        self.assertIsNotNone(error)

    async def test_list_without_dept_ids_errors(self):
        stub = SimpleNamespace(
            vemory_dept_ids="  ",
            vemory_page_size=50,
            vemory_max_pages=5,
            vemory_audio_cache_ttl=1800,
        )
        with patch("app.meeting.vemory.get_settings", return_value=stub):
            rows, error = await v.list_dealer_meetings("2026-09-01", "2026-09-30")
        self.assertEqual(rows, [])
        self.assertIn("PDCA_VEMORY_DEPT_IDS", error)


class VemoryDetailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        v.clear_cache()

    async def test_detail_ok_and_cached(self):
        fake = AsyncMock(
            return_value={
                "ok": True,
                "meeting": {"id": "m1", "summary": "纪要全文", "audio_url": "https://audio/m1.wav"},
            }
        )
        with patch("app.meeting.vemory.run_vertu_json", new=fake):
            meeting, error = await v.meeting_detail("m1")
            meeting2, error2 = await v.meeting_detail("m1")
        self.assertIsNone(error)
        self.assertIsNone(error2)
        self.assertEqual(meeting["summary"], "纪要全文")
        self.assertEqual(meeting2["summary"], "纪要全文")
        self.assertEqual(fake.await_count, 1)

    async def test_detail_returns_error_when_not_ok(self):
        fake = AsyncMock(return_value={"ok": False})
        with patch("app.meeting.vemory.run_vertu_json", new=fake):
            meeting, error = await v.meeting_detail("m1")
        self.assertIsNone(meeting)
        self.assertIn("失败", error)


class VemoryAudioLinksTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        v.clear_cache()
        self.list_calls = 0
        self.detail_calls = []

    def _fake_runner(self):
        async def fake(args, timeout=45.0):
            if args[1] == "+list":
                self.list_calls += 1
                return _list_payload([_row(1), _row(2), _row(3)], 3)
            mid = args[args.index("--meeting-id") + 1]
            self.detail_calls.append(mid)
            audio = f"https://audio/{mid}.wav" if mid in ("m1", "m2") else None
            return {"ok": True, "meeting": {"id": mid, "summary": "x", "audio_url": audio}}

        return fake

    async def test_audio_links_builds_and_caches(self):
        with patch("app.meeting.vemory.run_vertu_json", new=AsyncMock(side_effect=self._fake_runner())):
            links, error = await v.audio_links("2026-09-01", "2026-09-30")
            self.assertEqual(self.list_calls, 1)
            self.assertEqual(len(self.detail_calls), 3)
            links2, error2 = await v.audio_links("2026-09-01", "2026-09-30")
        self.assertIsNone(error)
        self.assertIsNone(error2)
        self.assertEqual(len(links), 2)
        self.assertEqual({item["meeting_id"] for item in links}, {"m1", "m2"})
        self.assertEqual(len(links2), 2)
        # 第二次命中缓存：不再拉列表与详情
        self.assertEqual(self.list_calls, 1)
        self.assertEqual(len(self.detail_calls), 3)

    async def test_audio_links_force_refreshes(self):
        with patch("app.meeting.vemory.run_vertu_json", new=AsyncMock(side_effect=self._fake_runner())):
            await v.audio_links("2026-09-01", "2026-09-30")
            await v.audio_links("2026-09-01", "2026-09-30", force=True)
        # force 绕过音频缓存重新拉列表；详情仍走详情缓存
        self.assertEqual(self.list_calls, 2)
        self.assertEqual(len(self.detail_calls), 3)

    async def test_audio_links_without_dept_ids_errors(self):
        stub = SimpleNamespace(
            vemory_dept_ids="  ",
            vemory_page_size=50,
            vemory_max_pages=5,
            vemory_audio_cache_ttl=1800,
        )
        with patch("app.meeting.vemory.get_settings", return_value=stub):
            links, error = await v.audio_links("2026-09-01", "2026-09-30")
        self.assertEqual(links, [])
        self.assertIn("PDCA_VEMORY_DEPT_IDS", error)


if __name__ == "__main__":
    unittest.main()
