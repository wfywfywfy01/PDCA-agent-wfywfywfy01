"""Import a verified, speaker-mapped Vemory transcript for review."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope
from app.database import get_session
from app.meeting import vemory as vemory_api
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaSegment, OmegaSession, utcnow
from app.omega.policy import require_case, require_session_source
from app.omega.router import canonical, digest, enabled, session_view

router = APIRouter(prefix="/api/omega", tags=["omega"])


class RealImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    meeting_id: str = Field(min_length=1, max_length=120)
    speaker_map: dict[str, Literal["sales", "counterparty"]]


def _source_keys(meeting: dict) -> set[str]:
    values = [meeting.get("owner_name"), meeting.get("owner")]
    for person in meeting.get("participants") or []:
        if isinstance(person, dict):
            values.extend(person.get(key) for key in ("name", "display_name", "login", "email"))
        else:
            values.append(person)
    return {normalize_scope_key(value) for value in values if normalize_scope_key(value)}


def _transcript(meeting: dict) -> list[dict]:
    source = meeting.get("transcript_segments") or meeting.get("transcript")
    if isinstance(source, dict):
        source = source.get("utterances") or source.get("segments")
    if not isinstance(source, list) or not source:
        raise HTTPException(422, "会议缺少可核验的分说话人逐字稿")
    result = []
    for item in source:
        if not isinstance(item, dict):
            raise HTTPException(422, "逐字稿片段格式无效")
        speaker = str(item.get("speaker") or item.get("speaker_name") or "").strip()
        content = str(item.get("text") or item.get("content") or "").strip()
        if not speaker or not content or len(content) > 4000:
            raise HTTPException(422, "逐字稿存在无说话人、空白或过长片段")
        result.append({"speaker": speaker, "text": content})
    if len(result) > 120 or sum(len(item["text"]) for item in result) > 24000:
        raise HTTPException(413, "逐字稿超出完整评估上限")
    return result


def _goal_timing(version: OmegaCaseVersion, meeting: dict) -> str:
    raw = meeting.get("start_time")
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if start.tzinfo is None:
            return "unknown"
        confirmed = version.created_at
        if confirmed.tzinfo is None:
            confirmed = confirmed.replace(tzinfo=timezone.utc)
        return "pre" if confirmed <= start else "post"
    except (TypeError, ValueError):
        return "unknown"


@router.post("/real-imports", status_code=201, dependencies=[Depends(enabled)])
async def import_real_meeting(
    body: RealImportRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    case = db.get(OmegaCase, body.case_id)
    require_case(user, db, case)
    if not case.current_version or case.confirmed_revision != case.revision:
        raise HTTPException(409, "先确认复盘目标")
    db.rollback()
    meeting, error = await vemory_api.meeting_detail(body.meeting_id)
    if error or not meeting:
        raise HTTPException(404, error or "会议不存在")
    case = db.exec(select(OmegaCase).where(
        OmegaCase.id == body.case_id,
    ).with_for_update().execution_options(populate_existing=True)).first()
    require_case(user, db, case)
    if not case.current_version or case.confirmed_revision != case.revision:
        raise HTTPException(409, "先确认复盘目标")
    if meeting.get("id") and str(meeting["id"]) != body.meeting_id:
        raise HTTPException(422, "会议来源标识不匹配")
    source_keys = _source_keys(meeting)
    if not source_keys:
        raise HTTPException(422, "会议没有可验证的归属或参与者")
    scope = resolve_data_scope(user, db)
    allowed = {normalize_scope_key(value) for value in scope.owner_keys}
    if not scope.unrestricted and not allowed.intersection(source_keys):
        raise HTTPException(403, "会议不在当前账号的数据权限范围内")
    transcript = _transcript(meeting)
    speakers = {item["speaker"] for item in transcript}
    if set(body.speaker_map) != speakers or set(body.speaker_map.values()) != {"sales", "counterparty"}:
        raise HTTPException(422, "须将所有说话人明确映射为销售或对手")
    version = db.exec(select(OmegaCaseVersion).where(
        OmegaCaseVersion.case_id == case.id,
        OmegaCaseVersion.version == case.current_version,
    )).one()
    source_hash = digest([case.id, body.meeting_id, version.content_hash,
                          body.speaker_map, transcript])
    existing = db.exec(select(OmegaSession).where(OmegaSession.source_import_hash == source_hash)).first()
    if existing:
        if existing.case_id != case.id:
            raise HTTPException(409, "会议导入冲突")
        require_session_source(user, db, existing)
        return session_view(db, existing)
    game = OmegaSession(
        case_id=case.id, case_version_id=version.id, team_key=case.team_key,
        owner_id=user.id, mode="real_review", status="ended",
        source_meeting_id=body.meeting_id, source_import_hash=source_hash,
        source_access_keys_json=canonical(sorted(source_keys)),
        goal_timing=_goal_timing(version, meeting), ended_at=utcnow(),
    )
    parts = [OmegaSegment(
        session_id=game.id, seq=index + 1, speaker=body.speaker_map[item["speaker"]],
        source="vemory", source_speaker=item["speaker"], text=item["text"],
    ) for index, item in enumerate(transcript)]
    game.transcript_hash = digest([[part.id, part.seq, part.speaker, part.text] for part in parts])
    try:
        db.add(game)
        db.flush()
        db.add_all(parts)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.exec(select(OmegaSession).where(OmegaSession.source_import_hash == source_hash)).first()
        if existing:
            if existing.case_id != case.id:
                raise HTTPException(409, "会议导入冲突")
            require_session_source(user, db, existing)
            return session_view(db, existing)
        raise HTTPException(409, "会议导入冲突") from None
    return session_view(db, game)
