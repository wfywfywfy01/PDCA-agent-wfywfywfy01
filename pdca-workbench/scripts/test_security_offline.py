"""Run PDCA security regressions with temporary storage and no external services.

Usage: python -B scripts/test_security_offline.py [unittest.module.or.test ...]
No .env files, real databases, network requests, or child processes are allowed.
"""
from __future__ import annotations

import logging
from importlib.util import find_spec
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def main() -> int:
    temporary = tempfile.TemporaryDirectory(prefix="pdca-security-offline-")
    root = Path(temporary.name).resolve()
    tempfile.tempdir = str(root)

    def inside(path) -> bool:
        return Path(path).resolve().is_relative_to(root)

    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = os.fsdecode(args[0])
            if Path(path).name == ".env":
                raise RuntimeError("Offline test guard: .env access denied")
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and not inside(path):
                raise RuntimeError("Offline test guard: write outside temporary directory")
        if event == "sqlite3.connect" and args[0] != ":memory:" and not inside(args[0]):
            raise RuntimeError("Offline test guard: non-test database")
        # Windows implements asyncio's private wake-up pipe as a loopback socketpair.
        if event == "socket.connect" and sys._getframe(1).f_code is getattr(socket, "_fallback_socketpair", lambda: None).__code__:
            return
        if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            raise RuntimeError("Offline test guard: external network/process")
        if event in {"os.mkdir", "os.remove", "os.rmdir"} and not inside(args[0]):
            raise RuntimeError("Offline test guard: filesystem change outside temporary directory")
        if event in {"os.rename", "os.replace"} and (not inside(args[0]) or not inside(args[1])):
            raise RuntimeError("Offline test guard: move outside temporary directory")

    sys.addaudithook(audit)
    safe_env = {key: os.environ[key] for key in (
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    ) if key in os.environ}
    safe_env.update(
        TEMP=str(root), TMP=str(root), PDCA_ENV="development", PDCA_DATABASE_URL="sqlite://",
        PDCA_AUTH_MODE="local", PDCA_SECRET_KEY="offline-test-key-never-for-production",
        PDCA_REQUIRE_VERTU="0", PDCA_SCHEDULER_ENABLED="0", PDCA_KNOWLEDGE_HUB_ENABLED="0",
        PDCA_MVP_ROOT=str(root / "mvp"), PDCA_REPO_ROOT=str(root / "repo"),
    )
    original_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path.resolve() == ROOT / "data":
            return None
        return original_mkdir(path, *args, **kwargs)

    with ExitStack() as patches:
        patches.enter_context(patch.dict(os.environ, safe_env, clear=True))
        patches.enter_context(patch("dotenv.load_dotenv", return_value=False))
        patches.enter_context(patch("pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_files", return_value={}))
        patches.enter_context(patch.object(Path, "mkdir", mkdir))
        # libpq opens sockets in native code, outside Python's socket audit hook.
        if find_spec("psycopg2") is not None:
            patches.enter_context(patch("psycopg2.connect", side_effect=RuntimeError("Offline test guard: PostgreSQL denied")))
        from app import config, database
        original_init = config.Settings.__init__

        def init(settings):
            original_init(settings)
            settings.data_dir = root / "data"
            settings.data_dir.mkdir(exist_ok=True)

        patches.enter_context(patch.object(config.Settings, "__init__", init))
        from sqlalchemy.pool import StaticPool
        from sqlmodel import SQLModel, create_engine
        database._engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        from loguru import logger
        logger.remove()
        logging.disable(logging.CRITICAL)
        explicit = sys.argv[1:]
        modules = explicit or [
            "tests.test_auth_hardening", "tests.test_knowledge_integration", "tests.test_knowledge_mcp",
            "tests.test_odoo_sso", "tests.test_security", "tests.test_auth_write_flows",
        ]

        def flatten(suite):
            for test in suite:
                if isinstance(test, unittest.TestSuite):
                    yield from flatten(test)
                else:
                    yield test

        selected = []
        for test in flatten(unittest.defaultTestLoader.loadTestsFromNames(modules)):
            name = test.id()
            if not explicit:
                if any(key in name for key in ("test_session_manager_survives_multiple_app_startups", "test_empty_customer_scope_returns_one_row_per_grade")):
                    continue
                if ".test_security." in name and not any(key in name for key in (
                    "scope_", "unconfigured_sales", "dealer_is_", "non_dealer_", "proxy_role_header", "security_headers",
                    "login_copy", "resolve_file_under", "view_path_rejects", "encoded_traversal",
                )):
                    continue
                if ".test_auth_write_flows." in name and not any(key in name for key in (
                    "login_success", "logout_revokes", "public_vps_probe", "forced_password", "representative_role",
                    "deactivate_dealer", "sales_accounts_cannot",
                )):
                    continue
            selected.append(test)
        SQLModel.metadata.create_all(database._engine)
        print("Offline tests: temporary SQLite; .env/network/subprocess/repository writes blocked")
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
        database._engine.dispose()
    temporary.cleanup()
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
