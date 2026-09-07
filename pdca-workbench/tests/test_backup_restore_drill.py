"""The restore drill must never drop a pre-existing database."""
from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import backup_restore_drill as drill


class BackupRestoreDrillTests(unittest.TestCase):
    def run_drill(self, *, keep=False, admin=None, query=None, restore=None):
        admin = admin or Mock(return_value=(0, ""))
        query = query or Mock(return_value=(0, "1\n"))
        restore = restore or Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        with ExitStack() as stack:
            stack.enter_context(patch.object(drill, "get_settings", return_value=SimpleNamespace(
                pg_connection_info={"host": "unit.invalid", "database": "production", "user": "unit"},
            )))
            stack.enter_context(patch.object(drill, "_find_psql", return_value="unit-psql"))
            stack.enter_context(patch.object(drill, "_latest_backup", return_value=Path(__file__)))
            stack.enter_context(patch.object(drill, "_admin_sql", new=admin))
            stack.enter_context(patch.object(drill, "_run_psql", new=query))
            # Also guard the legacy direct subprocess path: tests never access PostgreSQL.
            stack.enter_context(patch.object(drill.subprocess, "run", new=restore))
            stack.enter_context(patch.object(drill.sys, "argv", ["drill", *(["--keep-scratch"] if keep else [])]))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = drill.main()
        return result, admin, query

    def test_unique_database_created_before_any_drop_and_cleaned_on_success(self):
        names = []
        for _ in range(2):
            result, admin, query = self.run_drill()
            self.assertEqual(result, 0)
            commands = [call.args[2] for call in admin.call_args_list]
            self.assertEqual(len(commands), 2)
            self.assertTrue(commands[0].startswith("CREATE DATABASE "))
            name = commands[0].split()[-1]
            self.assertTrue(name.strip('"').startswith("pdca_restore_"))
            self.assertEqual(commands[1], f"DROP DATABASE {name}")
            self.assertTrue(all(call.args[2][1] == name.strip('"') for call in query.call_args_list))
            names.append(name)
        self.assertNotEqual(names[0], names[1])

    def test_failed_create_never_drops_an_existing_database(self):
        result, admin, _ = self.run_drill(admin=Mock(return_value=(1, "already exists")))
        self.assertEqual(result, 1)
        self.assertEqual(admin.call_count, 1)
        self.assertTrue(admin.call_args.args[2].startswith("CREATE DATABASE "))

    def test_restore_failure_and_timeout_cleanup_only_created_database(self):
        for query in (Mock(return_value=(1, "restore failed")), Mock(side_effect=subprocess.TimeoutExpired("unit-psql", 1))):
            with self.subTest(query=query):
                result, admin, _ = self.run_drill(query=query)
                self.assertEqual(result, 1)
                commands = [call.args[2] for call in admin.call_args_list]
                self.assertEqual(len(commands), 2)
                self.assertEqual(commands[1], commands[0].replace("CREATE DATABASE", "DROP DATABASE"))

    def test_keep_scratch_preserves_created_database_on_success_and_failure(self):
        for query, expected in ((Mock(return_value=(0, "1\n")), 0), (Mock(return_value=(1, "failed")), 1)):
            with self.subTest(expected=expected):
                result, admin, _ = self.run_drill(keep=True, query=query)
                self.assertEqual(result, expected)
                self.assertEqual(admin.call_count, 1)

    def test_zero_users_or_malformed_count_fails_validation(self):
        for count in ("0\n", "WARNING 12\n0\n"):
            with self.subTest(count=count):
                query = Mock(side_effect=lambda _psql, _info, args, **_kwargs: (
                    0, count if "SELECT count(*) FROM users" in args else "1\n",
                ))
                result, _, _ = self.run_drill(query=query)
                self.assertEqual(result, 1)

    def test_cleanup_failure_prevents_success(self):
        result, _, _ = self.run_drill(admin=Mock(side_effect=[(0, ""), (1, "drop denied")]))
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
