"""Durable model jobs. Model calls run outside database transactions."""
from __future__ import annotations

import json
import os
import time
import threading
from datetime import timedelta, timezone
from urllib.parse import urlsplit

import httpx
from loguru import logger
from sqlmodel import Session, select

from app.auth.models import User
from app.omega.context import actor_messages, coach_messages
from app.omega.models import (
    OmegaAssignment, OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaSegment,
    OmegaSession, new_id, utcnow,
    OmegaWorkerHeartbeat,
)
from app.omega.policy import require_case, require_session_source
from app.omega.reports import WEIGHTS, validate_report
from app.omega.router import digest, report_input_hash


def _default_generate(kind: str, messages: list[dict], max_tokens: int) -> str:
    provider = os.environ.get("PDCA_SUPERVISOR_PROVIDER", "").strip()
    model = os.environ.get("PDCA_SUPERVISOR_MODEL", "").strip()
    key = os.environ.get("PDCA_SUPERVISOR_API_KEY", "").strip()
    if not (provider.startswith("https://") and model and key):
        raise RuntimeError("Omega 文本模型未配置")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "temperature": 0.3 if kind in {"report", "draft"} else 0.8}
    if (kind == "report" and urlsplit(provider).hostname == "api.deepseek.com"
            and model.startswith("deepseek-")):
        payload.pop("temperature")
        payload.update(thinking={"type": "disabled"}, response_format={"type": "json_object"})
    response = httpx.post(
        provider.rstrip("/") + "/v1/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json=payload,
        timeout=90 if kind == "report" else 20,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("模型输出被截断")
    content = (choice["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError("模型没有返回正文")
    return content


def _segments(db: Session, session_id: str) -> list[dict]:
    rows = db.exec(select(OmegaSegment).where(
        OmegaSegment.session_id == session_id
    ).order_by(OmegaSegment.seq)).all()
    return [{"id": row.id, "speaker": row.speaker, "text": row.text} for row in rows]


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def run_once(engine, *, generate=_default_generate) -> bool:
    """Claim one job, then return whether a job was processed."""
    now = utcnow()
    with Session(engine) as db:
        expired = db.exec(select(OmegaJob).where(
            OmegaJob.status == "running", OmegaJob.kind.in_(["turn", "report"]),
            OmegaJob.lease_until < now,
        ).with_for_update(skip_locked=True)).all()
        for old in expired:
            old.status = "failed" if old.attempts >= 2 else "queued"
            old.lease_token = ""
            old.error = "任务租约过期" if old.status == "failed" else ""
        db.commit()
        job = db.exec(select(OmegaJob).where(
            OmegaJob.status == "queued", OmegaJob.kind.in_(["turn", "report"]),
            OmegaJob.available_at <= now,
        ).order_by(OmegaJob.priority.desc(), OmegaJob.created_at, OmegaJob.id)
            .with_for_update(skip_locked=True)).first()
        if job is None:
            return False
        token = new_id()
        job.status = "running"
        job.lease_token = token
        job.lease_until = now + timedelta(seconds=180)
        job.attempts += 1
        job.updated_at = now
        job_id, kind = job.id, job.kind
        db.commit()

    try:
        with Session(engine) as db:
            job = db.get(OmegaJob, job_id)
            game = db.get(OmegaSession, job.session_id)
            case = db.get(OmegaCase, game.case_id)
            owner = db.get(User, game.owner_id)
            if owner is None:
                raise ValueError("创建者账号已不存在")
            require_case(owner, db, case)
            require_session_source(owner, db, game)
            version = db.get(OmegaCaseVersion, game.case_version_id)
            snapshot = json.loads(version.snapshot_json)
            assignment = db.get(OmegaAssignment, game.assignment_id) if game.assignment_id else None
            focus = assignment.target_dimension if assignment else ""
            segments = _segments(db, game.id)
            if kind == "turn" and (game.status != "active" or game.revision != job.session_revision):
                raise ValueError("对话版本已失效")
            if kind == "report" and (game.status != "ended" or game.revision != job.session_revision
                                     or digest([[part["id"], index + 1, part["speaker"], part["text"]]
                                                for index, part in enumerate(segments)]) != game.transcript_hash
                                     or report_input_hash(game) != job.input_hash):
                raise ValueError("逐字稿已变化")
            session_id = game.id
            input_hash = job.input_hash
            expected_revision = game.revision
            goal_timing = game.goal_timing
        if kind == "turn":
            messages = actor_messages(snapshot, segments, focus=focus)
            result = generate(kind, messages, 1500)
            if not result or not result.strip():
                raise ValueError("模拟客户回复为空")
            result = result.strip()
            if len(result) > 4000:
                raise ValueError("模拟客户回复超出长度上限")
        elif kind == "report":
            weights = snapshot.get("score_weights", WEIGHTS)
            messages = coach_messages(snapshot, segments, weights, goal_timing=goal_timing)
            result = validate_report(generate(kind, messages, 8000), segments,
                                     goal_timing=goal_timing, weights=weights)
        else:
            raise ValueError("未知任务类型")

        with Session(engine) as db:
            game = db.exec(select(OmegaSession).where(
                OmegaSession.id == session_id
            ).with_for_update()).one()
            job = db.exec(select(OmegaJob).where(
                OmegaJob.id == job_id
            ).with_for_update()).one()
            if (job.status != "running" or job.lease_token != token
                    or _aware(job.lease_until) <= utcnow()
                    or game.revision != expected_revision):
                return True
            owner = db.get(User, game.owner_id)
            if owner is None:
                raise ValueError("创建者账号已不存在")
            require_case(owner, db, db.get(OmegaCase, game.case_id))
            require_session_source(owner, db, game)
            if kind == "turn":
                if game.status != "active":
                    return True
                count = len(_segments(db, session_id))
                db.add(OmegaSegment(session_id=session_id, seq=count + 1,
                                    speaker="counterparty", text=result,
                                    request_key=job.request_key))
                game.revision += 1
            else:
                if (game.status != "ended"
                        or report_input_hash(game) != input_hash):
                    return True
                report = OmegaReport(session_id=session_id, input_hash=input_hash,
                                     content_json=json.dumps(result, ensure_ascii=False),
                                     model=os.environ.get("PDCA_SUPERVISOR_MODEL", "test-model"),
                                     rubric_version="rubric-v2")
                db.add(report)
                job.result_id = report.id
            job.status = "succeeded"
            job.lease_token = ""
            job.updated_at = utcnow()
            db.commit()
        return True
    except Exception as exc:
        with Session(engine) as db:
            job = db.get(OmegaJob, job_id)
            if job and job.status == "running" and job.lease_token == token:
                retry = (kind == "report" and isinstance(exc, ValueError)
                         and str(exc) == "九维评分缺失" and job.attempts < 2)
                job.status = "queued" if retry else "failed"
                job.error = "" if retry else str(exc)[:300]
                job.lease_token = ""
                job.updated_at = utcnow()
                db.commit()
        return True


def serve_forever(engine, *, interval=0.5):
    worker_id = new_id()
    stop = threading.Event()

    def heartbeat():
        while not stop.is_set():
            try:
                with Session(engine) as db:
                    row = db.get(OmegaWorkerHeartbeat, worker_id)
                    if row is None:
                        row = OmegaWorkerHeartbeat(worker_id=worker_id)
                        db.add(row)
                    row.last_seen = utcnow()
                    db.commit()
            except Exception as exc:
                logger.warning("Omega worker heartbeat failed: {}", type(exc).__name__)
            stop.wait(5)

    thread = threading.Thread(target=heartbeat, name="omega-heartbeat", daemon=True)
    thread.start()
    try:
        while True:
            if not run_once(engine):
                time.sleep(interval)
    finally:
        stop.set()
        thread.join(timeout=2)
