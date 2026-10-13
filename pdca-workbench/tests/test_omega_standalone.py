"""An Omega web process must stay healthy when VPS authentication fails."""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine

from app.main import app, health, lifespan


@asynccontextmanager
async def _idle_manager():
    yield


class OmegaStandaloneTests(unittest.TestCase):
    def test_startup_and_health_do_not_depend_on_vps_or_backup(self):
        settings = SimpleNamespace(
            secret_key="test-only-secret-with-more-than-32-characters",
            environment="production", require_vertu=False, scheduler_enabled=False,
            host="127.0.0.1", port=8767, mvp_root="/unused", auth_mode="hybrid",
            vertu_command="vps-work",
        )
        engine = create_engine("sqlite://")
        try:
            with (
                patch.dict(os.environ, {}, clear=False),
                patch("app.main.setup_logging"),
                patch("app.main.get_settings", return_value=settings),
                patch("app.knowledge.client.validate_knowledge_hub_settings"),
                patch("app.main.bootstrap_database", return_value="sqlite"),
                patch("app.main.seed_users"),
                patch("app.models.store_seed.seed_stores"),
                patch("app.auth.scope.rebuild_all_dealer_assignments"),
                patch("app.database.get_engine", return_value=engine),
                patch("app.main.start_scheduler"),
                patch("app.main.stop_scheduler"),
                patch("app.main.backup_status", return_value={"ok": False}),
                patch("app.main.backup_database") as backup,
                patch("app.main.vertu_health", new_callable=AsyncMock) as vps,
                patch("app.main.get_db_mode", return_value="sqlite"),
                patch("app.main.check_db_connection", return_value=True),
                patch("app.main.knowledge_mcp.session_manager.run", side_effect=_idle_manager),
                patch("app.main.five_kit_mcp.session_manager.run", side_effect=_idle_manager),
            ):
                async def run():
                    async with lifespan(app):
                        response = await health()
                        self.assertEqual(response.status_code, 200)
                        payload = json.loads(response.body)
                        self.assertTrue(payload["backup"]["not_required"])
                        self.assertTrue(payload["vertu_cli"]["not_required"])

                asyncio.run(run())
                backup.assert_not_called()
                vps.assert_not_called()
        finally:
            engine.dispose()
