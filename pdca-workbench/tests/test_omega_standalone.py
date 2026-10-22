"""An Omega web process must stay healthy when VPS authentication fails."""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from app.main import app, health, lifespan
from app.omega.models import OmegaWorkerHeartbeat, utcnow


@asynccontextmanager
async def _idle_manager():
    yield


class OmegaStandaloneTests(unittest.TestCase):
    def test_health_requires_recent_worker_heartbeat_only_for_omega_web(self):
        settings = SimpleNamespace(environment="production", require_vertu=False, scheduler_enabled=False)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        OmegaWorkerHeartbeat.__table__.create(engine)
        try:
            with (
                patch.dict(os.environ, {"PDCA_OMEGA_ENABLED": "1"}),
                patch("app.main.get_settings", return_value=settings),
                patch("app.main.get_db_mode", return_value="postgresql"),
                patch("app.main.check_db_connection", return_value=True),
                patch("app.main.backup_status", return_value={"ok": False}),
                patch("app.main.get_engine", return_value=engine),
            ):
                missing = asyncio.run(health())
                self.assertEqual(missing.status_code, 503)
                self.assertFalse(json.loads(missing.body)["omega_worker"]["ok"])
                with Session(engine) as db:
                    db.add(OmegaWorkerHeartbeat(worker_id="stale", last_seen=utcnow() - timedelta(seconds=30)))
                    db.commit()
                stale = asyncio.run(health())
                self.assertEqual(stale.status_code, 503)
                with Session(engine) as db:
                    db.add(OmegaWorkerHeartbeat(worker_id="fresh", last_seen=utcnow()))
                    db.commit()
                fresh = asyncio.run(health())
                self.assertEqual(fresh.status_code, 200)
                self.assertTrue(json.loads(fresh.body)["omega_worker"]["ok"])
            with (
                patch.dict(os.environ, {"PDCA_OMEGA_ENABLED": "0"}),
                patch("app.main.get_settings", return_value=settings),
                patch("app.main.get_db_mode", return_value="postgresql"),
                patch("app.main.check_db_connection", return_value=True),
                patch("app.main.backup_status", return_value={"ok": False}),
                patch("app.main.get_engine", side_effect=AssertionError("worker query must be skipped")),
            ):
                other = asyncio.run(health())
                self.assertEqual(other.status_code, 200)
                self.assertTrue(json.loads(other.body)["omega_worker"]["not_required"])
            settings.scheduler_enabled = True
            with (
                patch.dict(os.environ, {"PDCA_OMEGA_ENABLED": "1"}),
                patch("app.main.get_settings", return_value=settings),
                patch("app.main.get_db_mode", return_value="postgresql"),
                patch("app.main.check_db_connection", return_value=True),
                patch("app.main.backup_status", return_value={"ok": True}),
                patch("app.main.get_engine", side_effect=AssertionError("main app must skip worker query")),
            ):
                main = asyncio.run(health())
                self.assertEqual(main.status_code, 200)
                self.assertTrue(json.loads(main.body)["omega_worker"]["not_required"])
        finally:
            engine.dispose()

    def test_health_worker_probe_failure_does_not_expose_error(self):
        settings = SimpleNamespace(environment="production", require_vertu=False, scheduler_enabled=False)
        with (
            patch.dict(os.environ, {"PDCA_OMEGA_ENABLED": "1"}),
            patch("app.main.get_settings", return_value=settings),
            patch("app.main.get_db_mode", return_value="postgresql"),
            patch("app.main.check_db_connection", return_value=True),
            patch("app.main.backup_status", return_value={"ok": False}),
            patch("app.main.get_engine", side_effect=RuntimeError("private-database-detail")),
        ):
            response = asyncio.run(health())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["omega_worker"]["state"], "unknown")
        self.assertNotIn(b"private-database-detail", response.body)

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
