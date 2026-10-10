"""Authenticated Omega HTTP entrypoints."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.omega.models import (
    OmegaAssignment, OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaReview, OmegaSegment,
    OmegaSession, OmegaWorkerHeartbeat, utcnow,
)
from app.omega.policy import require_case, require_session_source, require_team_user, require_writer
from app.omega.schemas import CaseCreate, CaseUpdate, DraftAnalysisRequest, OperationRequest, ReviewRequest, TurnRequest
from app.omega.reports import WEIGHTS
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/omega", tags=["omega"])


def is_enabled() -> bool:
    return os.environ.get("PDCA_OMEGA_ENABLED", "0").lower() in {"1", "true", "yes"}


def enabled() -> None:
    if not is_enabled():
        raise HTTPException(404, "Omega 未启用")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def transcript_digest(segments) -> str:
    rows = []
    identified = False
    for index, part in enumerate(segments):
        get = part.get if isinstance(part, dict) else lambda key, default=None: getattr(part, key, default)
        identity = [get("speaker_id"), get("turn_id"), get("provider_event_id")]
        identified = identified or any(identity)
        rows.append([get("id"), get("seq", index + 1), get("speaker"), get("text"), *identity])
    # Legacy transcripts have no participant/event identity; retain their existing hash.
    return digest(rows if identified else [row[:4] for row in rows])


def report_input_hash(game: OmegaSession) -> str:
    return digest([
        game.id, game.transcript_hash, game.case_version_id, game.goal_timing,
        game.context_snapshot_json, game.context_source_session_ids_json,
        "rubric-v2", "coach-v2", os.environ.get("PDCA_SUPERVISOR_PROVIDER", ""),
        os.environ.get("PDCA_SUPERVISOR_MODEL", ""),
        os.environ.get("PDCA_RELEASE_SHA", "dev"),
    ])


@router.get("/status")
def omega_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    require_team_user(user)
    flag = is_enabled()
    provider = os.environ.get("PDCA_SUPERVISOR_PROVIDER", "").strip()
    model_ready = bool(provider.startswith("https://")
                       and os.environ.get("PDCA_SUPERVISOR_MODEL", "").strip()
                       and os.environ.get("PDCA_SUPERVISOR_API_KEY", "").strip())
    worker_online = False
    from app.omega.realtime import configured as realtime_configured, multi_voice_ready
    voice_ready = realtime_configured()
    if flag:
        worker_online = db.exec(select(OmegaWorkerHeartbeat).where(
            OmegaWorkerHeartbeat.last_seen >= utcnow() - timedelta(seconds=20)
        ).limit(1)).first() is not None
    return {"enabled": flag, "ready": flag and (model_ready and worker_online or voice_ready),
            "model_configured": model_ready, "worker_online": worker_online,
            "realtime_configured": voice_ready, "multi_voice_ready": flag and multi_voice_ready(),
            "actor_id": user.id, "role": user.role}


def case_view(row: OmegaCase) -> dict:
    return {
        "id": row.id, "title": row.title, "team_key": row.team_key,
        "owner_id": row.owner_id, "dealer_id": row.dealer_id,
        "kind": row.kind, "opportunity_id": row.opportunity_id,
        "source_template_version_id": row.source_template_version_id,
        "revision": row.revision, "current_version": row.current_version,
        "draft_confirmed": bool(row.current_version and row.confirmed_revision == row.revision),
        "draft": json.loads(row.draft_json),
    }


@router.post("/case-draft/analyze", dependencies=[Depends(enabled)])
async def analyze_case_draft(
    body: DraftAnalysisRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    require_team_user(user)
    from app.omega import draft_assist

    if not draft_assist.available():
        raise HTTPException(503, "尚未配置 AI 分析模型")
    try:
        return await draft_assist.analyze(body.text)
    except Exception as exc:
        from loguru import logger
        logger.warning("Omega case draft analysis failed: {}", type(exc).__name__)
        raise HTTPException(502, "AI 分析失败，请补充描述后重试") from None


@router.post("/cases", status_code=201, dependencies=[Depends(enabled)])
def create_case(
    body: CaseCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    team = require_team_user(user)
    row = OmegaCase(
        team_key=team, owner_id=user.id, title=body.title,
        dealer_id=body.dealer_id, kind=body.kind, opportunity_id=body.opportunity_id,
        source_template_version_id=body.source_template_version_id,
        draft_json=canonical(body.model_dump(mode="json")),
    )
    require_case(user, db, row)
    db.add(row)
    db.commit()
    return case_view(row)


@router.get("/cases", dependencies=[Depends(enabled)])
def list_cases(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    team = require_team_user(user)
    rows = db.exec(select(OmegaCase).where(OmegaCase.team_key == team)).all()
    result = []
    for row in rows:
        try:
            require_case(user, db, row)
        except HTTPException:
            continue
        result.append(case_view(row))
    return result


@router.get("/cases/{case_id}", dependencies=[Depends(enabled)])
def get_case(
    case_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = db.get(OmegaCase, case_id)
    require_case(user, db, row)
    return case_view(row)


@router.patch("/cases/{case_id}", dependencies=[Depends(enabled)])
def update_case(
    case_id: str,
    body: CaseUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = db.exec(select(OmegaCase).where(OmegaCase.id == case_id).with_for_update()).first()
    require_case(user, db, row)
    require_writer(user, row.owner_id)
    if row.revision != body.revision:
        raise HTTPException(409, "任务已被更新，请刷新后重试")
    if ("source_template_version_id" in body.model_fields_set
            and body.source_template_version_id != row.source_template_version_id):
        raise HTTPException(422, "场景来源权限不可移除或替换")
    row.title = body.title
    row.dealer_id = body.dealer_id
    row.kind = body.kind
    row.opportunity_id = body.opportunity_id
    snapshot = body.model_dump(mode="json", exclude={"revision"})
    snapshot["source_template_version_id"] = row.source_template_version_id
    row.draft_json = canonical(snapshot)
    row.revision += 1
    row.updated_at = utcnow()
    require_case(user, db, row)
    db.commit()
    return case_view(row)


@router.post("/cases/{case_id}/confirm", dependencies=[Depends(enabled)])
def confirm_case(
    case_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = db.exec(select(OmegaCase).where(OmegaCase.id == case_id).with_for_update()).first()
    require_case(user, db, row)
    require_writer(user, row.owner_id)
    snapshot = json.loads(row.draft_json)
    if row.current_version:
        prior = db.exec(select(OmegaCaseVersion).where(
            OmegaCaseVersion.case_id == row.id,
            OmegaCaseVersion.version == row.current_version,
        )).one()
        if prior.content_hash == digest(snapshot):
            raise HTTPException(409, "当前内容已确认")
    next_version = row.current_version + 1
    version = OmegaCaseVersion(
        case_id=row.id, version=next_version, snapshot_json=canonical(snapshot),
        content_hash=digest(snapshot), confirmed_by=user.id,
    )
    db.add(version)
    row.current_version = next_version
    row.revision += 1
    row.confirmed_revision = row.revision
    row.updated_at = utcnow()
    db.commit()
    return {"id": version.id, "case_id": row.id, "version": next_version, "content_hash": version.content_hash}


class SessionCreate(BaseModel):
    case_id: str
    assignment_id: str | None = None


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    assignee_id: int
    source_report_id: str | None = None
    target_dimension: str
    pass_percent: int = Field(default=70, ge=1, le=100)
    instructions: str = Field(default="", max_length=1000)
    due_at: AwareDatetime | None = None


def dimension_result(report: OmegaReport | None, dimension: str) -> dict | None:
    if report is None:
        return None
    content = json.loads(report.content_json)
    weights = content.get("score_weights") or WEIGHTS
    maximum = weights.get(dimension)
    item = next((row for row in content.get("dimensions", [])
                 if row.get("key") == dimension), None)
    if not item or item.get("score") is None or not maximum:
        return None
    score = item["score"]
    return {"score": score, "maximum": maximum, "percent": round(score * 100 / maximum),
            "report_id": report.id}


def assignment_view(db: Session, row: OmegaAssignment) -> dict:
    source = db.get(OmegaReport, row.source_report_id) if row.source_report_id else None
    baseline = dimension_result(source, row.target_dimension)
    games = db.exec(select(OmegaSession).where(
        OmegaSession.assignment_id == row.id,
    ).order_by(OmegaSession.created_at)).all()
    attempts = []
    for game in games:
        report = db.exec(select(OmegaReport).where(
            OmegaReport.session_id == game.id,
        ).order_by(OmegaReport.created_at.desc()).limit(1)).first()
        score = dimension_result(report, row.target_dimension)
        attempts.append({"session_id": game.id, "status": game.status,
                         "result": score, "passed": bool(score and score["score"] * 100 >= row.pass_percent * score["maximum"])})
    return {"id": row.id, "case_id": row.case_id, "case_version_id": row.case_version_id,
            "assignee_id": row.assignee_id, "assigned_by": row.assigned_by,
            "source_report_id": row.source_report_id, "target_dimension": row.target_dimension,
            "pass_percent": row.pass_percent, "instructions": row.instructions,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "baseline": baseline, "attempts": attempts,
            "status": "passed" if any(item["passed"] for item in attempts)
                      else "in_progress" if attempts else "pending"}


def visible_assignment(db: Session, user: User, row: OmegaAssignment | None) -> OmegaAssignment:
    if row is None or row.team_key != require_team_user(user):
        raise HTTPException(404, "练习指派不存在")
    if user.id != row.assignee_id and user.role not in {"manager", "admin"}:
        raise HTTPException(404, "练习指派不存在")
    require_case(user, db, db.get(OmegaCase, row.case_id))
    if row.source_report_id:
        source = db.get(OmegaReport, row.source_report_id)
        if source is None:
            raise HTTPException(404, "来源报告不存在")
        owned_session(db, user, source.session_id)
    return row


@router.get("/team-members", dependencies=[Depends(enabled)])
def team_members(user: Annotated[User, Depends(get_current_user)],
                 db: Annotated[Session, Depends(get_session)]):
    team = require_team_user(user)
    if user.role not in {"manager", "admin"}:
        raise HTTPException(403, "仅同组主管可以查看可指派人员")
    rows = db.exec(select(User).where(User.team_key == team, User.is_active == True,
                                          User.role.in_(["sales", "manager", "admin"]))).all()
    return [{"id": row.id, "name": row.display_name or row.username} for row in rows]


@router.post("/assignments", status_code=201, dependencies=[Depends(enabled)])
def create_assignment(body: AssignmentCreate,
                      user: Annotated[User, Depends(get_current_user)],
                      db: Annotated[Session, Depends(get_session)]):
    team = require_team_user(user)
    self_practice = (user.role == "sales" and body.assignee_id == user.id
                     and body.source_report_id is not None)
    if user.role not in {"manager", "admin"} and not self_practice:
        raise HTTPException(403, "仅同组主管可以指派练习；销售只能从本人报告发起复练")
    if body.target_dimension not in WEIGHTS:
        raise HTTPException(422, "未知评分项")
    case = db.get(OmegaCase, body.case_id)
    require_case(user, db, case)
    assignee = db.get(User, body.assignee_id)
    if not assignee or not assignee.is_active or assignee.team_key != team or assignee.role not in {"sales", "manager", "admin"}:
        raise HTTPException(422, "被指派人不在当前团队")
    require_case(assignee, db, case)
    source = db.get(OmegaReport, body.source_report_id) if body.source_report_id else None
    if body.source_report_id:
        if source is None:
            raise HTTPException(404, "来源报告不存在")
        source_game = owned_session(db, user, source.session_id)
        if self_practice and source_game.owner_id != user.id:
            raise HTTPException(403, "销售只能从本人报告发起复练")
        if source_game.case_id != case.id:
            raise HTTPException(422, "来源报告与场景不一致")
        require_session_source(assignee, db, source_game)
        version_id = source_game.case_version_id
    else:
        if not case.current_version or case.confirmed_revision != case.revision:
            raise HTTPException(409, "先确认谈判目标")
        version = db.exec(select(OmegaCaseVersion).where(
            OmegaCaseVersion.case_id == case.id,
            OmegaCaseVersion.version == case.current_version,
        )).one()
        version_id = version.id
    row = OmegaAssignment(case_id=case.id, case_version_id=version_id,
                          team_key=team, assignee_id=assignee.id, assigned_by=user.id,
                          source_report_id=body.source_report_id,
                          target_dimension=body.target_dimension,
                          pass_percent=body.pass_percent, instructions=body.instructions,
                          due_at=body.due_at.astimezone(timezone.utc) if body.due_at else None)
    db.add(row)
    db.commit()
    return assignment_view(db, row)


@router.get("/assignments", dependencies=[Depends(enabled)])
def list_assignments(user: Annotated[User, Depends(get_current_user)],
                     db: Annotated[Session, Depends(get_session)]):
    team = require_team_user(user)
    rows = db.exec(select(OmegaAssignment).where(
        OmegaAssignment.team_key == team,
    ).order_by(OmegaAssignment.created_at.desc()).limit(100)).all()
    visible = []
    for row in rows:
        try:
            visible_assignment(db, user, row)
        except HTTPException:
            continue
        visible.append(assignment_view(db, row))
    return visible


@router.get("/assignments/{assignment_id}", dependencies=[Depends(enabled)])
def get_assignment(assignment_id: str,
                   user: Annotated[User, Depends(get_current_user)],
                   db: Annotated[Session, Depends(get_session)]):
    return assignment_view(db, visible_assignment(db, user, db.get(OmegaAssignment, assignment_id)))


def owned_session(db: Session, user: User, session_id: str) -> OmegaSession:
    row = db.get(OmegaSession, session_id)
    if row is None:
        raise HTTPException(404, "演练不存在")
    require_case(user, db, db.get(OmegaCase, row.case_id))
    require_session_source(user, db, row)
    return row


def session_segments(db: Session, session_id: str) -> list[OmegaSegment]:
    return list(db.exec(select(OmegaSegment).where(
        OmegaSegment.session_id == session_id
    ).order_by(OmegaSegment.seq)).all())


def session_view(db: Session, row: OmegaSession) -> dict:
    from app.omega.memory import session_snapshot
    version = db.get(OmegaCaseVersion, row.case_version_id)
    latest_report = db.exec(select(OmegaReport).where(
        OmegaReport.session_id == row.id
    ).order_by(OmegaReport.created_at.desc()).limit(1)).first()
    pending_job = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id,
        OmegaJob.kind.in_(["turn", "report"]),
        OmegaJob.status.in_(["queued", "running"]),
    ).order_by(OmegaJob.created_at.desc()).limit(1)).first()
    return {
        "id": row.id, "case_id": row.case_id, "mode": row.mode,
        "assignment_id": row.assignment_id,
        "case_version_id": row.case_version_id,
        "case_version": version.version if version else None,
        "case_snapshot": session_snapshot(row, version) if version else None,
        "source_meeting_id": row.source_meeting_id, "goal_timing": row.goal_timing,
        "status": row.status, "owner_id": row.owner_id,
        "voice_state": row.voice_state, "audio_epoch": row.audio_epoch,
        "revision": row.revision, "transcript_hash": row.transcript_hash,
        "latest_report_id": latest_report.id if latest_report else "",
        "pending_job_id": pending_job.id if pending_job else "",
        "segments": [
            {"id": segment.id, "seq": segment.seq, "speaker": segment.speaker,
             "text": segment.text, "source": segment.source,
             "asr_original": segment.asr_original,
             "source_speaker": segment.source_speaker, "speaker_id": segment.speaker_id,
             "turn_id": segment.turn_id, "provider_event_id": segment.provider_event_id}
            for segment in session_segments(db, row.id)
        ],
    }


@router.post("/sessions", status_code=201, dependencies=[Depends(enabled)])
def create_session(
    body: SessionCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    case = db.get(OmegaCase, body.case_id)
    require_case(user, db, case)
    if case.kind == "template":
        raise HTTPException(409, "请从预设开始，保留模板并创建本次副本")
    assignment = db.get(OmegaAssignment, body.assignment_id) if body.assignment_id else None
    if body.assignment_id:
        if (assignment is None or assignment.case_id != case.id
                or assignment.team_key != case.team_key or assignment.assignee_id != user.id):
            raise HTTPException(404, "练习指派不存在")
        visible_assignment(db, user, assignment)
        version = db.get(OmegaCaseVersion, assignment.case_version_id)
    else:
        if not case.current_version or case.confirmed_revision != case.revision:
            raise HTTPException(409, "先确认谈判目标")
        version = db.exec(select(OmegaCaseVersion).where(
            OmegaCaseVersion.case_id == case.id,
            OmegaCaseVersion.version == case.current_version,
        )).one()
    from app.omega.memory import create_context_snapshot
    snapshot = json.loads(version.snapshot_json)
    if snapshot.get("usage") == "real_review":
        if assignment is None:
            raise HTTPException(409, "真实会议复盘须导入已有会议")
        snapshot.update(usage="rehearsal", simulation=True)
    context_json, source_ids_json = create_context_snapshot(db, user, case, snapshot)
    row = OmegaSession(case_id=case.id, case_version_id=version.id,
                       team_key=case.team_key, owner_id=user.id,
                       assignment_id=assignment.id if assignment else None,
                       mode=snapshot.get("usage", "rehearsal"), context_snapshot_json=context_json,
                       context_source_session_ids_json=source_ids_json)
    db.add(row)
    db.commit()
    return session_view(db, row)


@router.get("/sessions/{session_id}", dependencies=[Depends(enabled)])
def get_session_view(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    return session_view(db, owned_session(db, user, session_id))


@router.get("/sessions", dependencies=[Depends(enabled)])
def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    team = require_team_user(user)
    rows = db.exec(select(OmegaSession).where(
        OmegaSession.team_key == team
    ).order_by(OmegaSession.created_at.desc()).limit(100)).all()
    visible = []
    for row in rows:
        try:
            require_case(user, db, db.get(OmegaCase, row.case_id))
            require_session_source(user, db, row)
        except HTTPException:
            continue
        visible.append({"id": row.id, "case_id": row.case_id, "owner_id": row.owner_id,
                        "mode": row.mode, "status": row.status,
                        "created_at": row.created_at.isoformat()})
    return visible


def job_view(row: OmegaJob) -> dict:
    return {"id": row.id, "session_id": row.session_id, "kind": row.kind,
            "request_key": row.request_key, "status": row.status,
            "result_id": row.result_id, "error": row.error}


@router.post("/sessions/{session_id}/turns", status_code=202, dependencies=[Depends(enabled)])
def submit_turn(
    session_id: str,
    body: TurnRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = owned_session(db, user, session_id)
    row = db.exec(select(OmegaSession).where(OmegaSession.id == row.id)
                  .with_for_update().execution_options(populate_existing=True)).one()
    require_writer(user, row.owner_id)
    request_hash = digest(body.model_dump())
    existing = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "turn",
        OmegaJob.request_key == body.request_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "相同请求编号的内容不同")
        return job_view(existing)
    if row.status != "active":
        raise HTTPException(409, "演练已经结束")
    live = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "realtime",
        OmegaJob.status == "running", OmegaJob.lease_until > utcnow(),
    )).first()
    if live:
        raise HTTPException(409, "实时语音正在进行，请先挂断")
    pending = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "turn",
        OmegaJob.status.in_(["queued", "running"]),
    )).first()
    if pending:
        raise HTTPException(409, "上一轮仍在处理")
    segments = session_segments(db, row.id)
    if len(segments) >= 120 or sum(len(part.text) for part in segments) + len(body.text) > 24000:
        raise HTTPException(413, "本场演练已达长度上限，请结束并复盘")
    part = OmegaSegment(session_id=row.id, seq=len(segments) + 1,
                        speaker="sales", text=body.text.strip(),
                        source=body.source, asr_original=body.asr_original,
                        request_key=body.request_key, speaker_id="sales",
                        turn_id=body.request_key, provider_event_id=body.request_key)
    row.revision += 1
    job = OmegaJob(session_id=row.id, kind="turn", request_key=body.request_key,
                   request_hash=request_hash, input_hash=digest([row.case_version_id, body.text, row.revision]),
                   session_revision=row.revision, priority=10)
    db.add(part)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.exec(select(OmegaJob).where(
            OmegaJob.session_id == row.id, OmegaJob.kind == "turn",
            OmegaJob.request_key == body.request_key,
        )).first()
        if existing and existing.request_hash == request_hash:
            return job_view(existing)
        raise HTTPException(409, "上一轮仍在处理") from None
    return job_view(job)


@router.get("/jobs/{job_id}", dependencies=[Depends(enabled)])
def get_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    job = db.get(OmegaJob, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    owned_session(db, user, job.session_id)
    return job_view(job)


@router.post("/sessions/{session_id}/finish", dependencies=[Depends(enabled)])
def finish_session(
    session_id: str,
    body: OperationRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = owned_session(db, user, session_id)
    row = db.exec(select(OmegaSession).where(OmegaSession.id == row.id)
                  .with_for_update().execution_options(populate_existing=True)).one()
    require_writer(user, row.owner_id)
    require_complete_voice_tail(db, row)
    if row.status == "ended":
        if session_segments(db, row.id):
            enqueue_report(db, row)
            db.commit()
        return session_view(db, row)
    realtime = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "realtime", OmegaJob.status == "running",
    )).first()
    if realtime:
        raise HTTPException(409, "实时语音尾部尚未保存，请等待连接关闭后再结束")
    for job in db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id,
        OmegaJob.kind.in_(["turn", "realtime"]),
        OmegaJob.status.in_(["queued", "running"]),
    )).all():
        job.status = "cancelled"
        job.lease_token = ""
    row.status = "ended"
    row.revision += 1
    row.ended_at = utcnow()
    row.transcript_hash = transcript_digest(session_segments(db, row.id))
    if session_segments(db, row.id):
        enqueue_report(db, row)
    db.commit()
    return session_view(db, row)


def require_complete_voice_tail(db: Session, row: OmegaSession) -> None:
    incomplete = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "realtime",
        OmegaJob.error == "语音尾稿未完成，请检查逐字稿后重新演练",
    )).first()
    if incomplete:
        raise HTTPException(409, incomplete.error)


def enqueue_report(db: Session, row: OmegaSession, request_key: str | None = None) -> OmegaJob:
    """Caller holds the session lock and commits with transcript/state changes."""
    require_complete_voice_tail(db, row)
    from app.omega.coaching import report_hints_metadata
    from app.omega.memory import session_snapshot
    snapshot = session_snapshot(row, db.get(OmegaCaseVersion, row.case_version_id))
    if "report_hints_used" not in snapshot:
        snapshot["report_hints_used"] = report_hints_metadata(db, row)
        row.context_snapshot_json = canonical(snapshot)
    request_hash = report_input_hash(row)
    request_key = request_key or "auto-report-" + request_hash
    existing = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "report", OmegaJob.request_key == request_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "场景数据已变化，请使用新的请求编号")
        return existing
    same_input = db.exec(select(OmegaJob).where(
        OmegaJob.session_id == row.id, OmegaJob.kind == "report", OmegaJob.input_hash == request_hash,
        OmegaJob.status.in_(["queued", "running", "succeeded"]),
    ).order_by(OmegaJob.created_at.desc()).limit(1)).first()
    if same_input:
        return same_input
    job = OmegaJob(session_id=row.id, kind="report", request_key=request_key,
                   request_hash=request_hash, input_hash=request_hash,
                   session_revision=row.revision, priority=1)
    db.add(job)
    return job


@router.post("/sessions/{session_id}/reports", status_code=202, dependencies=[Depends(enabled)])
def request_report(
    session_id: str,
    body: OperationRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    row = owned_session(db, user, session_id)
    row = db.exec(select(OmegaSession).where(OmegaSession.id == row.id)
                  .with_for_update().execution_options(populate_existing=True)).one()
    require_writer(user, row.owner_id)
    if row.status != "ended":
        raise HTTPException(409, "先结束演练")
    if not session_segments(db, row.id):
        raise HTTPException(409, "还没有对话")
    job = enqueue_report(db, row, body.request_key)
    request_hash = job.input_hash
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        same_input = db.exec(select(OmegaJob).where(
            OmegaJob.session_id == row.id, OmegaJob.kind == "report",
            OmegaJob.input_hash == request_hash,
            OmegaJob.status.in_(["queued", "running", "succeeded"]),
        )).first()
        if same_input:
            return job_view(same_input)
        raise HTTPException(409, "报告请求冲突") from None
    return job_view(job)


@router.get("/reports/{report_id}", dependencies=[Depends(enabled)])
def get_report(
    report_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    report = db.get(OmegaReport, report_id)
    if report is None:
        raise HTTPException(404, "报告不存在")
    owned_session(db, user, report.session_id)
    reviews = db.exec(select(OmegaReview).where(
        OmegaReview.report_id == report.id
    ).order_by(OmegaReview.created_at)).all()
    from app.omega.reports import report_summary
    content = json.loads(report.content_json)
    content["summary"] = report_summary(content)
    return {"id": report.id, "session_id": report.session_id,
            "content": content, "model": report.model,
            "reviews": [{"id": item.id, "reviewer_id": item.reviewer_id,
                         "content": json.loads(item.content_json)} for item in reviews]}


@router.post("/reports/{report_id}/reviews", status_code=201, dependencies=[Depends(enabled)])
def add_review(
    report_id: str,
    body: ReviewRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    report = db.get(OmegaReport, report_id)
    if report is None:
        raise HTTPException(404, "报告不存在")
    owned_session(db, user, report.session_id)
    if user.role not in {"manager", "admin"}:
        raise HTTPException(403, "仅同组主管可以点评")
    review = OmegaReview(report_id=report.id, reviewer_id=user.id,
                         content_json=canonical(body.model_dump()))
    db.add(review)
    db.commit()
    return {"id": review.id, "report_id": report.id,
            "reviewer_id": review.reviewer_id, "content": body.model_dump()}
