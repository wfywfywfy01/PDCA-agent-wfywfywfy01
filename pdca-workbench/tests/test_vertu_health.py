import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.vertu import client


class VertuHealthTests(unittest.TestCase):
    def setUp(self):
        client._HEALTH_CACHE.update({"ts": 0.0, "value": None})

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
        self.assertEqual(result["detail"], "vertu-cli 凭据不可用")


if __name__ == "__main__":
    unittest.main()
