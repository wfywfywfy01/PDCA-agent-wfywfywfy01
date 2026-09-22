from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class MigrationEntrypointTests(unittest.TestCase):
    def test_unversioned_history_runs_post_baseline_migrations(self):
        root = Path(__file__).resolve().parents[1]
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
            env = os.environ.copy()
            env.update({
                "PDCA_DATABASE_URL": f"sqlite:///{database.as_posix()}",
                "PDCA_SCHEDULER_ENABLED": "0",
                "PDCA_SECRET_KEY": "migration-test-only-secret",
            })
            result = subprocess.run(
                [sys.executable, "scripts/migrate.py"], cwd=root, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60,
            )
            self.assertEqual(
                result.returncode,
                0,
                (result.stdout or "") + (result.stderr or ""),
            )
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
            self.assertEqual(version, "014")
            self.assertIn("uq_meeting_records_external_id", {row[1] for row in indexes})
            self.assertEqual(rows, [("new",)])


if __name__ == "__main__":
    unittest.main()
