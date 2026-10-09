from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def migration_head():
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def migration_env(url):
    return dict(os.environ, PDCA_ENV="development", PDCA_DATABASE_URL=url,
                PDCA_SCHEDULER_ENABLED="0", PDCA_SECRET_KEY="migration-test-only-secret",
                PYTHONIOENCODING="utf-8")


def run_migration(test, env, *arguments):
    command = [sys.executable, *arguments] if arguments else [sys.executable, "scripts/migrate.py"]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60, **flags)
    test.assertEqual(result.returncode, 0, (result.stdout or "") + (result.stderr or ""))


class MigrationEntrypointTests(unittest.TestCase):
    def test_unversioned_history_runs_post_baseline_migrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "history.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("""
                    CREATE TABLE meeting_records (
                        id INTEGER PRIMARY KEY,
                        meeting_date VARCHAR(10) NOT NULL,
                        external_id VARCHAR(64) NOT NULL,
                        title VARCHAR(512), meeting_type VARCHAR(32), bucket VARCHAR(32),
                        duration_minutes INTEGER, brief TEXT, todos_json TEXT,
                        participants_json TEXT, synced_at TIMESTAMP
                    )
                """)
                connection.executemany(
                    "INSERT INTO meeting_records "
                    "(meeting_date, external_id, title, synced_at) VALUES (?, ?, ?, ?)",
                    [
                        ("2026-09-20", "same-id", "old", "2026-09-20 01:00:00"),
                        ("2026-09-21", "same-id", "new", "2026-09-21 01:00:00"),
                        ("2026-09-19", "same-id", "undated", None),
                    ],
                )
                connection.commit()
            env = migration_env(f"sqlite:///{database.as_posix()}")
            run_migration(self, env)
            run_migration(self, env)
            with closing(sqlite3.connect(database)) as connection:
                version = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0]
                indexes = connection.execute(
                    "PRAGMA index_list('meeting_records')"
                ).fetchall()
                rows = connection.execute(
                    "SELECT title FROM meeting_records WHERE external_id='same-id'"
                ).fetchall()
            self.assertEqual(version, migration_head())
            self.assertIn("uq_meeting_records_external_id", {row[1] for row in indexes})
            self.assertEqual(rows, [("new",)])
            self.assert_memory_schema(database)
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "018")
            run_migration(self, env)
            self.assert_memory_schema(database)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT title FROM meeting_records WHERE external_id='same-id'").fetchall(), [("new",)])

    def assert_memory_schema(self, database):
        with closing(sqlite3.connect(database)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"omega_opportunities", "omega_memory_profiles", "omega_memory_proposals",
                             "omega_memory_entries", "omega_coach_hints"} <= tables)
            foreign_keys = connection.execute("PRAGMA foreign_key_list('omega_cases')").fetchall()
            self.assertTrue(any(row[2] == "omega_opportunities" and row[3] == "opportunity_id" for row in foreign_keys))
            indexes = {row[1] for row in connection.execute("PRAGMA index_list('omega_jobs')")}
            self.assertIn("uq_omega_active_memory_input", indexes)
            columns = {row[1] for row in connection.execute("PRAGMA table_info('omega_sessions')")}
            self.assertTrue({"context_snapshot_json", "context_source_session_ids_json", "voice_state"} <= columns)

    def test_fresh_sqlite_018_to_head_roundtrip_preserves_legacy_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "fresh.sqlite"
            env = migration_env(f"sqlite:///{database.as_posix()}")
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "018")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("""INSERT INTO omega_cases
                    (id,team_key,owner_id,title,dealer_id,draft_json,revision,current_version,
                     confirmed_revision,created_at,updated_at)
                    VALUES ('migration-legacy-case','migration-team',1,'Preserve history','','{}',1,0,0,
                            '2026-10-09 00:00:00+00:00','2026-10-09 00:00:00+00:00')""")
                connection.commit()
            run_migration(self, env)
            run_migration(self, env)
            self.assert_memory_schema(database)
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "018")
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT title FROM omega_cases WHERE id='migration-legacy-case'").fetchone(), ("Preserve history",))
                self.assertNotIn("opportunity_id", {row[1] for row in connection.execute("PRAGMA table_info('omega_cases')")})
            run_migration(self, env)
            self.assert_memory_schema(database)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT title FROM omega_cases WHERE id='migration-legacy-case'").fetchone(), ("Preserve history",))

    def test_partially_applied_memory_column_repairs_foreign_key_and_repeated_upgrade(self):
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import create_engine
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "partial.sqlite"
            url = f"sqlite:///{database.as_posix()}"
            env = migration_env(url)
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "019")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("ALTER TABLE omega_cases ADD COLUMN opportunity_id VARCHAR(36)")
                connection.commit()
            run_migration(self, env)
            self.assert_memory_schema(database)
            spec = importlib.util.spec_from_file_location("memory_migration", ROOT / "migrations" / "versions" / "020_omega_memory.py")
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            engine = create_engine(url)
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql("DROP INDEX uq_omega_active_memory_input")
                    with Operations.context(MigrationContext.configure(connection)):
                        migration.upgrade()
                        migration.upgrade()
            finally:
                engine.dispose()
            self.assert_memory_schema(database)


@unittest.skipUnless(os.environ.get("OMEGA_TEST_DATABASE_URL"), "disposable PostgreSQL URL not configured")
class PostgreSQLMigrationEntrypointTests(unittest.TestCase):
    def test_unversioned_history_is_idempotent_and_roundtrips(self):
        from uuid import uuid4
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.schema import CreateSchema, DropSchema
        url = make_url(os.environ["OMEGA_TEST_DATABASE_URL"])
        if (os.environ.get("PDCA_ENV") != "development" or url.get_backend_name() != "postgresql"
                or url.host not in {"127.0.0.1", "localhost"} or url.database != "omega_test"):
            raise RuntimeError("Migration test requires isolated local development omega_test")
        engine = create_engine(url)
        schema = "omega_migration_" + uuid4().hex
        schema_engine = None
        try:
            with engine.begin() as connection:
                connection.execute(CreateSchema(schema))
                connection.execute(text(f"CREATE TABLE {schema}.meeting_records ("
                    "id SERIAL PRIMARY KEY,meeting_date VARCHAR(10) NOT NULL,external_id VARCHAR(64) NOT NULL,"
                    "title VARCHAR(512),meeting_type VARCHAR(32),bucket VARCHAR(32),duration_minutes INTEGER,"
                    "brief TEXT,todos_json TEXT,participants_json TEXT,synced_at TIMESTAMP)"))
                connection.execute(text(f"INSERT INTO {schema}.meeting_records (meeting_date,external_id,title,synced_at) VALUES "
                    "('2026-09-20','same-id','old','2026-09-20 01:00:00'),"
                    "('2026-09-21','same-id','new','2026-09-21 01:00:00')"))
            env = migration_env(url.render_as_string(hide_password=False))
            env["PGOPTIONS"] = f"-csearch_path={schema}"
            schema_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
            run_migration(self, env)
            run_migration(self, env)
            with schema_engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), migration_head())
                self.assertEqual(connection.execute(text("SELECT title FROM meeting_records WHERE external_id='same-id'")).all(), [("new",)])
                constraints = inspect(connection).get_foreign_keys("omega_cases")
                self.assertTrue(any(row["constrained_columns"] == ["opportunity_id"] for row in constraints))
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "018")
            run_migration(self, env)
            with schema_engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), migration_head())
                self.assertEqual(connection.execute(text("SELECT title FROM meeting_records WHERE external_id='same-id'")).all(), [("new",)])
        finally:
            if schema_engine:
                schema_engine.dispose()
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
