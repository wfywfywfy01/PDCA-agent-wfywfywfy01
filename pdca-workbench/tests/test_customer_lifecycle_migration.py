import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tests.test_migrate_entrypoint import migration_env, migration_head, run_migration


class CustomerLifecycleMigrationTests(unittest.TestCase):
    def test_upgrade_from_025_and_repeat_preserve_customer_and_unique_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lifecycle.sqlite"
            env = migration_env(f"sqlite:///{path.as_posix()}")
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "025")
            with closing(sqlite3.connect(path)) as db:
                self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='lifecycle_customers'").fetchall())
            run_migration(self, env)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone()[0], migration_head())
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"lifecycle_customers", "lifecycle_identities", "lifecycle_evidence",
                                 "lifecycle_proposals", "lifecycle_business_links", "lifecycle_audit"} <= tables)
                columns = {r[1] for r in db.execute("PRAGMA table_info('lifecycle_evidence')")}
                self.assertTrue({"source_message_key", "occurred_at", "ingested_at"} <= columns)
                constraints = []
                for index in db.execute("PRAGMA index_list('lifecycle_evidence')").fetchall():
                    if index[2]:
                        constraints.append(tuple(r[2] for r in db.execute(f"PRAGMA index_info('{index[1]}')")))
                self.assertIn(("source_system", "event_id"), constraints)
                self.assertIn(("source_message_key",), constraints)
                db.execute("""INSERT INTO lifecycle_customers
                    (id,name,owner_user_id,team_key,route,assisted_routes_json,source_note,country,entity_verified,stage,
                     highest_stage,decision_maker,need,next_action,version,created_at,updated_at)
                    VALUES ('customer-preserved','Preserve',1,'A',NULL,'[]','','',0,'pending','pending','','','',1,
                            '2026-10-01 00:00:00','2026-10-01 00:00:00')""")
                db.commit()
            run_migration(self, env)
            run_migration(self, env, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "025")
            run_migration(self, env)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT name FROM lifecycle_customers WHERE id='customer-preserved'").fetchone()[0], "Preserve")
