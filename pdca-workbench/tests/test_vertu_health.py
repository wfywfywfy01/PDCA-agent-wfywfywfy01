import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.config import resolve_cli_command
from app.vertu import client


class VertuHealthTests(unittest.TestCase):
    def setUp(self):
        client._HEALTH_CACHE.update({"ts": 0.0, "value": None})
        client._MISSING_COMMANDS.clear()

    def test_unknown_command_is_cached(self):
        try:
            with patch(
                "app.vertu.client.run_vertu",
                new=AsyncMock(return_value=(1, "", "error: unknown command 'meeting'")),
            ) as run:
                first = asyncio.run(client.run_vertu_json(["meeting", "+list"]))
                second = asyncio.run(client.run_vertu_json(["meeting", "+list"]))
            self.assertIsNone(first)
            self.assertIsNone(second)
            run.assert_awaited_once()
            self.assertTrue(client.cli_command_missing("meeting"))
        finally:
            client._MISSING_COMMANDS.clear()

    def test_stale_vertu_cli_env_uses_vps_work(self):
        def fake_which(name: str):
            if name == "vps-work":
                return r"C:\npm\vps-work.cmd"
            if name == "vertu-cli":
                return r"C:\npm\vertu-cli.cmd"
            return None

        with patch.dict(os.environ, {"VERTU_COMMAND": "vertu-cli"}), patch(
            "app.config.shutil.which", side_effect=fake_which
        ):
            self.assertEqual(resolve_cli_command(), r"C:\npm\vps-work.cmd")

    def test_agent_environment_is_verified_with_server_scopes(self):
        payload = (
            '{"login":"may","agentAppId":"cursor",'
            '"userScopes":["sales.headline_kpi:read"]}'
        )
        with (
            patch("app.vertu.client.resolve_vertu_command", return_value="/usr/bin/vertu-cli"),
            patch("app.vertu.client.Path.is_file", return_value=True),
            patch(
                "app.vertu.client.run_vertu",
                new=AsyncMock(return_value=(0, payload, "")),
            ) as run,
        ):
            result = asyncio.run(client.vertu_health(force=True))

        run.assert_awaited_once_with(["auth", "scopes", "--json"], timeout=12.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["auth_mode"], "agent")
        self.assertTrue(result["never_expires"])

    def test_missing_server_identity_is_rejected(self):
        with (
            patch("app.vertu.client.resolve_vertu_command", return_value="/usr/bin/vertu-cli"),
            patch("app.vertu.client.Path.is_file", return_value=True),
            patch(
                "app.vertu.client.run_vertu",
                new=AsyncMock(return_value=(0, '{"userScopes":[]}', "")),
            ),
        ):
            result = asyncio.run(client.vertu_health(force=True))

        self.assertFalse(result["ok"])
        # CLI 已改名（vertu-cli -> vps-work），这里只校验后缀，避免绑死环境里的可执行名
        self.assertIn("凭据不可用", result["detail"])


if __name__ == "__main__":
    unittest.main()
