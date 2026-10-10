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
from app.omega.context import actor_messages, audit_messages, coach_messages, practice_messages, select_next_speaker
from app.omega.models import (
    OmegaAssignment, OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaSegment,
    OmegaSession, new_id, utcnow,
    OmegaWorkerHeartbeat,
)
from app.omega.policy import require_case, require_session_source
from app.omega.reports import WEIGHTS, report_audit_claims, report_summary, validate_next_practice, validate_report, validate_report_audit
from app.omega.router import digest, report_input_hash, transcript_digest


def _default_generate(kind: str, messages: list[dict], max_tokens: int) -> str:
    provider = os.environ.get("PDCA_SUPERVISOR_PROVIDER", "").strip()
    model = os.environ.get("PDCA_SUPERVISOR_MODEL", "").strip()
    key = os.environ.get("PDCA_SUPERVISOR_API_KEY", "").strip()
    if not (provider.startswith("https://") and model and key):
        raise RuntimeError("Omega 文本模型未配置")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "temperature": 0.3 if kind in {"report", "draft", "memory"} else 0.8}
    timeout = 90 if kind in {"report", "memory"} else 20
    if (urlsplit(provider).hostname == "api.deepseek.com"
            and model.startswith("deepseek-")):
        payload.pop("temperature")
        reasoning = kind in {"report", "report_audit", "practice"}
        payload["thinking"] = {"type": "enabled" if reasoning else "disabled"}
        if reasoning:
            payload["reasoning_effort"] = "high"
            timeout = {"report": 90, "report_audit": 150, "practice": 30}[kind]
        if kind in {"report", "report_audit", "memory", "practice"}:
            payload["response_format"] = {"type": "json_object"}
    response = httpx.post(
        provider.rstrip("/") + "/v1/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        if kind == "report_audit":
            raise ValueError("复盘事实核验无效")
        raise RuntimeError("模型输出被截断")
    content = (choice["message"].get("content") or "").strip()
    if not content:
        if kind == "report_audit":
            raise ValueError("复盘事实核验无效")
        raise RuntimeError("模型没有返回正文")
    return content


def _segments(db: Session, session_id: str) -> list[dict]:
    rows = db.exec(select(OmegaSegment).where(
        OmegaSegment.session_id == session_id
    ).order_by(OmegaSegment.seq)).all()
    return [{"id": row.id, "speaker": row.speaker, "text": row.text,
             "speaker_id": row.speaker_id, "turn_id": row.turn_id,
             "provider_event_id": row.provider_event_id} for row in rows]


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _report_call_allowed(engine, job_id, token, session_id, revision, input_hash) -> bool:
    """Revalidate the lease, frozen input and current source permissions between calls."""
    with Session(engine) as db:
        job = db.get(OmegaJob, job_id)
        if (job is None or job.status != "running" or job.lease_token != token
                or not job.lease_until or _aware(job.lease_until) <= utcnow()):
            return False
        game = db.get(OmegaSession, session_id)
        if (game is None or game.status != "ended" or game.revision != revision
                or report_input_hash(game) != input_hash
                or transcript_digest(_segments(db, session_id)) != game.transcript_hash):
            raise ValueError("逐字稿已变化")
        owner = db.get(User, game.owner_id)
        if owner is None:
            raise ValueError("创建者账号已不存在")
        if not owner.is_active:
            raise ValueError("创建者账号已停用")
        require_session_source(owner, db, game)
    return True


def run_once(engine, *, generate=_default_generate) -> bool:
    """Claim one job, then return whether a job was processed."""
    from app.omega.coaching import run_once as run_coach_once
    from app.omega.memory import enqueue_memory_job, finish_memory_job, prepare_memory_job, session_snapshot
    if run_coach_once(engine, generate=generate):
        return True
    now = utcnow()
    with Session(engine) as db:
        expired = db.exec(select(OmegaJob).where(
            OmegaJob.status == "running", OmegaJob.kind.in_(["turn", "report", "memory"]),
            OmegaJob.lease_until < now,
        ).with_for_update(skip_locked=True)).all()
        for old in expired:
            old.status = "failed" if old.attempts >= 2 else "queued"
            old.lease_token = ""
            old.error = "任务租约过期" if old.status == "failed" else ""
        db.commit()
        job = db.exec(select(OmegaJob).where(
            OmegaJob.status == "queued", OmegaJob.kind.in_(["turn", "report", "memory"]),
            OmegaJob.available_at <= now,
        ).order_by(OmegaJob.priority.desc(), OmegaJob.created_at, OmegaJob.id)
            .with_for_update(skip_locked=True)).first()
        if job is None:
            return False
        token = new_id()
        job.status = "running"
        job.lease_token = token
        job.lease_until = now + timedelta(seconds=300 if job.kind == "report" else 180)
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
            if kind == "report" and not owner.is_active:
                raise ValueError("创建者账号已停用")
            require_case(owner, db, case)
            require_session_source(owner, db, game)
            version = db.get(OmegaCaseVersion, game.case_version_id)
            snapshot = session_snapshot(game, version)
            assignment = db.get(OmegaAssignment, game.assignment_id) if game.assignment_id else None
            focus = assignment.target_dimension if assignment else ""
            segments = _segments(db, game.id)
            if kind == "turn" and (game.status != "active" or game.revision != job.session_revision):
                raise ValueError("对话版本已失效")
            if kind == "report" and (game.status != "ended" or game.revision != job.session_revision
                                     or transcript_digest(segments) != game.transcript_hash
                                     or report_input_hash(game) != job.input_hash):
                raise ValueError("逐字稿已变化")
            session_id = game.id
            input_hash = job.input_hash
            expected_revision = game.revision
            goal_timing = game.goal_timing
            if kind == "memory":
                memory_messages = prepare_memory_job(db, owner, job)
                db.commit()
            if kind == "report":
                hints_used = snapshot.get("report_hints_used", [])
        if kind == "turn":
            selected_speaker = select_next_speaker(snapshot, segments)
            turn_id = next((part.get("turn_id") for part in reversed(segments) if part["speaker"] == "sales"), None)
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
            result = validate_report(generate(kind, messages, 16384), segments,
                                     goal_timing=goal_timing, weights=weights)
            report_audit_claims(result)
            if not _report_call_allowed(engine, job_id, token, session_id, expected_revision, input_hash):
                return True
            result["next_practice"] = ""
            if report_summary(result)["blocker"]:
                result["next_practice"] = validate_next_practice(generate(
                    "practice", practice_messages(snapshot, segments, result), 4096))
            result["summary"] = report_summary(result)
            if not _report_call_allowed(engine, job_id, token, session_id, expected_revision, input_hash):
                return True
            validate_report_audit(generate("report_audit", audit_messages(
                segments, result, include_practice=True), 32768), result, include_practice=True)
            if not _report_call_allowed(engine, job_id, token, session_id, expected_revision, input_hash):
                return True
            result["hints_used"] = hints_used
        elif kind == "memory":
            result = generate(kind, memory_messages, 4000)
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
            if kind == "report" and not owner.is_active:
                raise ValueError("创建者账号已停用")
            require_case(owner, db, db.get(OmegaCase, game.case_id))
            require_session_source(owner, db, game)
            if kind == "turn":
                if game.status != "active":
                    return True
                count = len(_segments(db, session_id))
                db.add(OmegaSegment(session_id=session_id, seq=count + 1,
                                    speaker="counterparty", text=result,
                                    request_key=job.request_key, speaker_id=selected_speaker["id"],
                                    turn_id=turn_id or job.request_key, provider_event_id=job.id))
                game.revision += 1
            elif kind == "report":
                if (game.status != "ended"
                        or report_input_hash(game) != input_hash):
                    return True
                if transcript_digest(_segments(db, session_id)) != game.transcript_hash:
                    raise ValueError("逐字稿已变化")
                report = OmegaReport(session_id=session_id, input_hash=input_hash,
                                     content_json=json.dumps(result, ensure_ascii=False),
                                     model=os.environ.get("PDCA_SUPERVISOR_MODEL", "test-model"),
                                     rubric_version="rubric-v2", prompt_version="coach-v4")
                db.add(report)
                job.result_id = report.id
                published_report_id, published_owner_id = report.id, owner.id
            else:
                proposal = finish_memory_job(db, owner, job, result)
                job.result_id = proposal.id
            job.status = "succeeded"
            job.lease_token = ""
            job.updated_at = utcnow()
            db.commit()
        if kind == "report":
            # Report publication is durable even when memory preparation fails.
            try:
                with Session(engine) as db:
                    report = db.get(OmegaReport, published_report_id)
                    owner = db.get(User, published_owner_id)
                    enqueue_memory_job(db, owner, report, "auto-" + report.id)
                    db.commit()
            except Exception as exc:
                logger.warning("Omega memory enqueue failed: {}", type(exc).__name__)
        return True
    except Exception as exc:
        with Session(engine) as db:
            job = db.get(OmegaJob, job_id)
            if job and job.status == "running" and job.lease_token == token:
                retry = (kind == "report" and isinstance(exc, ValueError)
                         and str(exc) in {"九维评分缺失", "销售评价缺少销售原话", "引文与当前逐字稿不匹配", "下轮练习建议无效",
                                          "复盘事实核验未通过", "复盘事实核验无效"}
                         and job.attempts < 2)
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
