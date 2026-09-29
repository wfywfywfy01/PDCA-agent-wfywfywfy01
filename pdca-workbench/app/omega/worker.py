"""Dedicated Omega queue worker. Start only after the schema migration."""
from __future__ import annotations

import os

from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine
from app.omega.jobs import serve_forever
from app.omega.router import is_enabled


def main() -> None:
    if not is_enabled():
        raise SystemExit("PDCA_OMEGA_ENABLED must be 1 for the worker")
    settings = get_settings()
    if settings.environment == "production" and not settings.database_url.startswith("postgresql"):
        raise SystemExit("production Omega worker requires PostgreSQL")
    if not all(os.environ.get(name, "").strip() for name in (
        "PDCA_SUPERVISOR_PROVIDER", "PDCA_SUPERVISOR_MODEL", "PDCA_SUPERVISOR_API_KEY",
    )):
        raise SystemExit("Omega model provider is not configured")
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1 FROM omega_jobs LIMIT 1"))
    try:
        serve_forever(engine)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
