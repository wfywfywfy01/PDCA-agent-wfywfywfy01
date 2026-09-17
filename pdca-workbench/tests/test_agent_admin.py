# -*- coding: utf-8 -*-
"""Agent 管理后台：服务层与注册表单测。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.agent_admin import registry, service
from app.agent_admin.router import BotCreateIn

BOTS_JSON = (
    '{"items": [{"id": "1", "app_id": "vbot_A", "name": "测试机器人", '
    '"is_public": false, "active": true}]}'
)
CHANNELS_JSON = (
    '{"channels": [{"app_id": "vbot_A", "channel_id": "ch-1", "channel_name": "测试群"}], '
    '"robot_total": 1, "total": 1}'
)


def _run(coro):
    return asyncio.run(coro)


class BotsServiceTests(unittest.TestCase):
    def test_list_bots_parses_items(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(0, BOTS_JSON, "")),
        ) as run:
            items = _run(service.list_bots())
        run.assert_awaited_once_with(["im", "+bots"], timeout=60.0)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["app_id"], "vbot_A")

    def test_list_bots_raises_on_empty_output(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(1, "", "vertu-cli 认证失败")),
        ):
            with self.assertRaises(service.BotAdminError):
                _run(service.list_bots())

    def test_create_bot_builds_args_and_flags(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(0, '{"ok": true}', "")),
        ) as run:
            result = _run(
                service.create_bot(
                    service.BotCreateSpec(
                        name="新机器人",
                        bot_key="my-bot-01",
                        description="说明",
                        webhook_url="https://example.com/hook",
                        public=True,
                    )
                )
            )
        args = run.await_args.args[0]
        self.assertEqual(args[0:4], ["im", "+bot-create", "--name", "新机器人"])
        self.assertIn("--bot-key", args)
        self.assertIn("--description", args)
        self.assertIn("--webhook-url", args)
        self.assertIn("--public", args)
        self.assertEqual(result, {"ok": True})

    def test_set_bot_visibility_private_flag(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(0, '{"ok": true}', "")),
        ) as run:
            _run(service.set_bot_visibility("vbot_A", public=False))
        args = run.await_args.args[0]
        self.assertEqual(
            args, ["im", "+bot-update", "--app-id", "vbot_A", "--private"]
        )

    def test_list_bot_channels_parses_channels_key(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(0, CHANNELS_JSON, "")),
        ):
            items = _run(service.list_bot_channels())
        self.assertEqual(items[0]["channel_name"], "测试群")
        self.assertEqual(items[0]["app_id"], "vbot_A")

    def test_list_bot_channels_items_fallback(self):
        with patch(
            "app.agent_admin.service.run_vertu",
            new=AsyncMock(return_value=(0, '{"items": [{"channel_id": "ch-2"}]}', "")),
        ):
            items = _run(service.list_bot_channels())
        self.assertEqual(len(items), 1)


class BotCreateValidationTests(unittest.TestCase):
    def test_name_blank_rejected(self):
        with self.assertRaises(ValidationError):
            BotCreateIn.model_validate({"name": "   "})

    def test_bot_key_shape_rejected(self):
        with self.assertRaises(ValidationError):
            BotCreateIn.model_validate({"name": "OK", "bot_key": "bad key!"})

    def test_webhook_scheme_rejected(self):
        with self.assertRaises(ValidationError):
            BotCreateIn.model_validate({"name": "OK", "webhook_url": "ftp://x"})

    def test_valid_payload_passes(self):
        body = BotCreateIn.model_validate(
            {
                "name": " 新机器人 ",
                "bot_key": "my-bot-01",
                "description": "说明",
                "webhook_url": "https://example.com/hook",
                "public": True,
            }
        )
        self.assertEqual(body.name, "新机器人")
        self.assertTrue(body.public)


class RegistryTests(unittest.TestCase):
    def test_pdca_agents_cover_seven_roles(self):
        agents = registry.pdca_agents_snapshot()
        self.assertEqual(len(agents), 7)
        keys = {item["key"] for item in agents}
        self.assertEqual(
            keys,
            {
                "team-pdca-planner",
                "daily-sales-log-checker",
                "team-kpi-checker",
                "customer-coverage-checker",
                "pdca-action-agent",
                "coaching-agent",
                "quota-allocation-agent",
            },
        )
        for item in agents:
            self.assertTrue(item["name"])
            self.assertTrue(item["role"])
            self.assertIn(item["status"], {"active", "planned"})

    def test_model_routing_snapshot_reads_env(self):
        with patch.dict(
            "os.environ",
            {"PDCA_SUPERVISOR_PROVIDER": "https://api.deepseek.com", "PDCA_SUPERVISOR_MODEL": "deepseek-flash"},
            clear=False,
        ):
            routing = registry.model_routing_snapshot()
        text_rule = next(item for item in routing if item["task"] == "text")
        vision_rule = next(item for item in routing if item["task"] == "vision")
        self.assertTrue(text_rule["configured"])
        self.assertEqual(text_rule["model"], "deepseek-flash")
        self.assertIn("qwen", vision_rule["default_note"])


if __name__ == "__main__":
    unittest.main()
