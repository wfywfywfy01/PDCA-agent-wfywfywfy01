# -*- coding: utf-8 -*-
"""外发定时任务的 at-most-once 运行凭证。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_engine
from app.models.scheduled_job_run import ScheduledJobRun

# claim 后进程异常退出（被杀/断电/重启）时，超时的 sending 记录按失败回收，
# 允许后续触发（如补发兜底轮）重新执行；正常执行时长（<10 分钟）远小于该窗口。
_STALE_SENDING_SECONDS = 30 * 60


def claim_run(job_name: str, bucket: str) -> bool:
    run_key = f"{job_name}:{bucket}"
    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        existing = session.exec(
            select(ScheduledJobRun).where(ScheduledJobRun.run_key == run_key)
        ).first()
        if existing is not None:
            if existing.status == "sending" and existing.started_at is not None:
                started = existing.started_at
                if started.tzinfo is None:
                    # SQLite 回读丢失时区；本表只写 UTC，按 UTC 处理。
                    started = started.replace(tzinfo=timezone.utc)
                if now - started <= timedelta(seconds=_STALE_SENDING_SECONDS):
                    return False
                # 超时回收：复用同一行重新认领（新建行会撞 run_key 唯一约束）。
                existing.status = "sending"
                existing.detail = ""
                existing.started_at = now
                existing.finished_at = None
                session.add(existing)
                session.commit()
                return True
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
