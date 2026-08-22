# Runbook

## Routine checks

- PDCA `/health` and data-hub `/health/ready` return `200`.
- `/metrics` is scraped from the private network.
- Sales users see only assigned dealers; out-of-scope requests fail closed.
- Search results include source file, version, and page or media timestamp.
- Sales original export returns `403`; admin export requires a reason and creates an audit event.
- PostgreSQL backups run daily and a disposable restore drill runs monthly.

## Incident

1. Stop the failing import, worker, or release.
2. Record commit, request ID, actor, time window, affected dealer, and row/asset counts.
3. Preserve failed inputs and logs outside Git.
4. Roll back the app or restore/rerun the idempotent data pipeline.
5. Add a regression test and update `PROGRESS.md`.
