# -*- coding: utf-8 -*-
"""2026-09-23：早会待办自动取数（张洪姣私聊 -> 本地 Qwen OCR -> 第 8 节）的回归。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock


class ParseItemsTests(unittest.TestCase):
    def test_headers_numbered_and_who_lines(self):
        from app.meeting_todos_fetch import parse_items

        text = (
            "2026.9.23 经销商早\n"
            "【经销商】\n"
            "- 重点：四季度思考：1.购物季怎么发挥经销商的能动性。\n"
            "【付汪洋】\n"
            "1. 内容中心把机器人加进去。\n"
            "2. 协助viki做投资数据\n"
            "尤文静：给伊朗的信要写完\n"
            "看不清\n"
        )
        items = parse_items(text)
        pairs = [(i["who"], i["text"]) for i in items]
        self.assertIn(("经销商", "重点：四季度思考：1.购物季怎么发挥经销商的能动性。"), pairs)
        self.assertIn(("付汪洋", "内容中心把机器人加进去。"), pairs)
        self.assertIn(("尤文静", "给伊朗的信要写完"), pairs)
        self.assertEqual(len(pairs), len(set(pairs)), "同一条不能重复")
        self.assertFalse(any("看不清" in text for _, text in pairs))

    def test_scope_mapping(self):
        from app.meeting_todos_fetch import attach_scope

        rows = attach_scope([
            {"who": "尤文静", "text": "伊朗信"},
            {"who": "付汪洋", "text": "六条线索"},
            {"who": "JIM", "text": "腕表规划"},
        ])
        by_who = {row["who"]: row for row in rows}
        self.assertEqual(by_who["尤文静"]["scope"], "group")
        self.assertIn("viki业绩达标群", by_who["尤文静"]["groups"])
        self.assertEqual(by_who["付汪洋"]["scope"], "mgmt")
        self.assertEqual(by_who["JIM"]["scope"], "mgmt")


class RuntimeFileTests(unittest.TestCase):
    def test_runtime_file_wins_over_repo_file(self):
        from app import meeting_todos

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            day_dir = root / "runtime" / "meeting_todos"
            day_dir.mkdir(parents=True)
            (day_dir / "2026-09-23.json").write_text(
                json.dumps(
                    {
                        "day": "2026-09-23",
                        "items": [
                            {"who": "尤文静", "text": "运行时条目", "scope": "group", "groups": ["viki业绩达标群"]}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fake = mock.Mock(data_dir=root)
            with mock.patch.object(meeting_todos, "get_settings", lambda: fake):
                block = meeting_todos.block_for_group("2026-09-23", "viki业绩达标群")
                mgmt = meeting_todos.block_for_mgmt("2026-09-23")
        self.assertIn("运行时条目", block)
        self.assertEqual(mgmt, "", "group 条目不能进管理版")


class FetchDayTests(unittest.TestCase):
    def test_uses_latest_image_and_falls_back(self):
        from app import meeting_todos_fetch as fetch

        images = [
            {"id": "old00000", "created_at": "2026-09-23T02:40:00Z", "url": "/a"},
            {"id": "new00000", "created_at": "2026-09-23T03:06:00Z", "url": "/b"},
        ]
        seen: list[str] = []

        def fake_ocr(path: pathlib.Path) -> str:
            seen.append(path.name)
            if "new00000" in path.name:
                return ""  # 最新一张读不出 -> 应该回退到旧的一张
            return "【尤文静】\n1. 给伊朗的信要写完\n"

        with mock.patch.object(fetch, "resolve_channel", lambda *a, **k: "chan"), mock.patch.object(
            fetch, "day_images", lambda *a, **k: images
        ), mock.patch.object(
            fetch, "download", lambda url, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"x"), True)[-1]
        ), mock.patch.object(fetch, "ocr_image", fake_ocr):
            result = fetch.fetch_day("2026-09-23")
        self.assertTrue(seen and "new00000" in seen[0], "先试最新一张")
        self.assertGreaterEqual(len(seen), 2, "最新读不出要回退")
        items = result["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["who"], "尤文静")
        self.assertEqual(items[0]["scope"], "group")

    def test_no_images_returns_empty(self):
        from app import meeting_todos_fetch as fetch

        with mock.patch.object(fetch, "resolve_channel", lambda *a, **k: "chan"), mock.patch.object(
            fetch, "day_images", lambda *a, **k: []
        ):
            result = fetch.fetch_day("2026-01-01")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["images"], 0)


if __name__ == "__main__":
    unittest.main()
