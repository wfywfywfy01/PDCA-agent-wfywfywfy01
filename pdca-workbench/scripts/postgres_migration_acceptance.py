"""Exercise real migrations only in the disposable Docker smoke databases."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.database import get_engine


def main() -> None:
    settings = get_settings()
    engine = get_engine()
    if (settings.environment != "development" or settings.scheduler_enabled
            or engine.url.database != "pdca_review"
            or engine.dialect.name != "postgresql"):
        raise RuntimeError("Refusing non-disposable database")
    if inspect(engine).get_table_names():
        raise RuntimeError("Migration acceptance requires an empty smoke database")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()

    def run(target, *args: str) -> None:
        env = dict(os.environ, PDCA_DATABASE_URL=target.url.render_as_string(hide_password=False))
        result = subprocess.run(
            [sys.executable, *args], cwd=root, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def verify(target) -> None:
        with target.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == head
        schema = inspect(target)
        assert "remind_send_id" in {c["name"] for c in schema.get_columns("todo_replies")}
        assert any(i["name"] == "uq_meeting_records_external_id" and i["unique"]
                   for i in schema.get_indexes("meeting_records"))

    for _ in range(2):
        run(engine, "scripts/migrate.py")
        verify(engine)
    print("PASS: empty PostgreSQL migration and repeated upgrade")
    run(engine, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "013")
    run(engine, "scripts/migrate.py")
    verify(engine)
    print("PASS: PostgreSQL 013 upgrade")

    # The dedicated Docker DB container owns both databases and removes them on exit.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CREATE DATABASE pdca_review_history"))
    history = create_engine(engine.url.set(database="pdca_review_history"))
    try:
        with history.begin() as connection:
            connection.execute(text("""CREATE TABLE meeting_records (
                id SERIAL PRIMARY KEY, meeting_date VARCHAR(10) NOT NULL,
                external_id VARCHAR(64) NOT NULL, title VARCHAR(512),
                meeting_type VARCHAR(32), bucket VARCHAR(32), duration_minutes INTEGER,
                brief TEXT, todos_json TEXT, participants_json TEXT, synced_at TIMESTAMP
            )"""))
            connection.execute(text("""INSERT INTO meeting_records
                (meeting_date, external_id, title, synced_at) VALUES
                ('2026-09-20', 'same-id', 'old', '2026-09-20 01:00:00'),
                ('2026-09-21', 'same-id', 'new', '2026-09-21 01:00:00'),
                ('2026-09-19', 'same-id', 'undated', NULL)"""))
        for _ in range(2):
            run(history, "scripts/migrate.py")
            verify(history)
        with history.connect() as connection:
            assert connection.execute(text("SELECT title FROM meeting_records")).scalars().all() == ["new"]
        print("PASS: unversioned PostgreSQL history keeps newest meeting and upgrades idempotently")
    finally:
        history.dispose()


if __name__ == "__main__":
    main()
