"""Read-only operational health, separate from process readiness."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

from sqlalchemy import case, func, select

from app.config import get_settings
from app.database import get_engine
from app.models.scheduled_job_run import ScheduledJobRun
from app.scheduler.run_ledger import _STALE_SENDING_SECONDS


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def job_status() -> dict:
    """Latest attempt per job; a successful retry resolves an earlier failure."""
    now = datetime.now(timezone.utc)
    run = ScheduledJobRun
    ranked = select(
        run.job_name, run.status, run.started_at, run.finished_at,
        func.max(case((run.status == "sent", run.finished_at))).over(
            partition_by=run.job_name).label("last_success_at"),
        func.row_number().over(partition_by=run.job_name,
            order_by=(run.started_at.desc(), run.id.desc())).label("rank"),
    ).subquery()
    try:
        with get_engine().connect() as connection:
            rows = connection.execute(select(ranked).where(ranked.c.rank == 1)).mappings().all()
        items = []
        for row in rows:
            started = _utc(row["started_at"])
            finished = _utc(row["finished_at"])
            stale = row["status"] == "sending" and (now-started).total_seconds() > _STALE_SENDING_SECONDS
            failed = row["status"] == "failed" and (finished or started) >= now-timedelta(hours=24)
            items.append({
                "job_name": row["job_name"], "status": row["status"],
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat() if finished else None,
                "last_success_at": _utc(row["last_success_at"]).isoformat() if row["last_success_at"] else None,
                "stale": stale, "failed": failed,
            })
        failed_count = sum(item["failed"] for item in items)
        stale_count = sum(item["stale"] for item in items)
        return {"ok": not failed_count and not stale_count, "state": "available",
                "failed_count": failed_count, "stale_count": stale_count, "items": items}
    except Exception as exc:
        return {"ok": False, "state": "unknown", "error": type(exc).__name__,
                "failed_count": None, "stale_count": None, "items": []}


def disk_status(path: Path) -> dict:
    """Application/backup filesystem; never performs cleanup."""
    try:
        disk = shutil.disk_usage(path)
        percent = round(100 * disk.free / disk.total, 1)
        return {"ok": percent >= 20, "state": "critical" if percent < 12 else "warning" if percent < 20 else "ok",
                "free_bytes": disk.free, "total_bytes": disk.total, "free_percent": percent}
    except (OSError, ZeroDivisionError) as exc:
        return {"ok": False, "state": "unknown", "error": type(exc).__name__,
                "free_bytes": None, "total_bytes": None, "free_percent": None}


def runtime_status() -> dict:
    settings = get_settings()
    jobs = job_status() if settings.scheduler_enabled else {
        "ok": True, "not_required": True, "state": "disabled",
        "failed_count": None, "stale_count": None, "items": [],
    }
    return {"jobs": jobs, "disk": disk_status(settings.data_dir)}
