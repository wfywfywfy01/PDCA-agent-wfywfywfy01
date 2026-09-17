# -*- coding: utf-8 -*-
"""草稿持久化与文本模型客户端的健壮性测试。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.group_context import GroupConfig
from app.agents.group_service import list_drafts, persist_draft
from app.agents.llm_client import QwenClient, QwenUnavailable
from app.agents.models import AgentDraft


def _config() -> GroupConfig:
    return GroupConfig(
        group_type="performance",
        channel_id="channel-draft",
        timezone="Asia/Shanghai",
        language="zh",
        owners=("于冰",),
        slot="20:00",
        date="2026-09-17",
        group_name="于冰业绩达标群",
    )


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()

    def tearDown(self):
        self.patch_engine.stop()
        self.engine.dispose()

    def test_persist_then_upsert_same_key(self):
        first = persist_draft(
            config=_config(),
            day="2026-09-17",
            slot="20:00",
            body="第一版草稿",
            approval_policy="auto_template",
            shadow=True,
        )
        second = persist_draft(
            config=_config(),
            day="2026-09-17",
            slot="20:00",
            body="第二版草稿",
            approval_policy="manual_required",
            shadow=False,
        )
        self.assertEqual(first, second)
        with Session(self.engine) as session:
            rows = session.exec(select(AgentDraft)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "第二版草稿")
        self.assertFalse(rows[0].shadow)

    def test_list_drafts_filters_by_day(self):
        persist_draft(
            config=_config(), day="2026-09-17", slot="20:00",
            body="a", approval_policy="manual_required", shadow=True,
        )
        items = list_drafts(day="2026-09-17")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["group_name"], "于冰业绩达标群")
        self.assertEqual(list_drafts(day="2026-09-16"), [])


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _empty_content_response():
    return _FakeResponse(200, {
        "choices": [{"finish_reason": "length", "message": {"content": ""}}],
        "usage": {"total_tokens": 4096},
    })


def _content_response(content):
    return _FakeResponse(200, {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"total_tokens": 100},
    })


class LlmClientTests(unittest.TestCase):
    def setUp(self):
        self.client = QwenClient(
            base_url="https://api.deepseek.com",
            api_key="test-key",
            model="deepseek-flash",
            timeout_seconds=10.0,
        )

    def test_empty_content_steers_once_then_succeeds(self):
        with patch(
            "httpx.post",
            side_effect=[_empty_content_response(), _content_response("最终答案")],
        ) as post_mock:
            reply = self.client.chat([{"role": "user", "content": "任务"}], max_tokens=2000)
        self.assertEqual(reply["content"], "最终答案")
        self.assertEqual(post_mock.call_count, 2)
        # 第二次请求带上“直接输出”引导
        steered = post_mock.call_args_list[1].kwargs["json"]["messages"][-1]["content"]
        self.assertIn("直接输出", steered)

    def test_persistent_empty_content_raises(self):
        with patch(
            "httpx.post", side_effect=[_empty_content_response()] * 3
        ):
            with self.assertRaises(QwenUnavailable) as ctx:
                self.client.chat([{"role": "user", "content": "任务"}], max_tokens=2000)
        self.assertIn("空内容", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
