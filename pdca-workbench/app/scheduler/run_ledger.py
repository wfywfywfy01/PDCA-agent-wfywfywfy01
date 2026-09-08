# -*- coding: utf-8 -*-
"""外发定时任务的 at-most-once 运行凭证。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_engine
from app.models.scheduled_job_run import ScheduledJobRun


def claim_run(job_name: str, bucket: str) -> bool:
    run_key = f"{job_name}:{bucket}"
    with Session(get_engine()) as session:
        if session.exec(
            select(ScheduledJobRun).where(ScheduledJobRun.run_key == run_key)
        ).first():
            return False
        session.add(ScheduledJobRun(
            run_key=run_key, job_name=job_name, bucket=bucket, status="sending"
        ))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True


def finish_run(job_name: str, bucket: str, status: str, detail: str = "") -> None:
    run_key = f"{job_name}:{bucket}"
    with Session(get_engine()) as session:
        row = session.exec(
            select(ScheduledJobRun).where(ScheduledJobRun.run_key == run_key)
        ).first()
        if row is None:
            return
        row.status = status[:16]
        row.detail = detail[:512]
        row.finished_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
