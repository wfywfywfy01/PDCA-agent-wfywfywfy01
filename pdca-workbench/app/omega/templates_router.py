"""Authenticated reusable preset endpoints."""
import json
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.omega.models import OmegaCase, OmegaCaseVersion
from app.omega.materials import MAX_UPLOAD_BYTES, extract_material
from app.omega.policy import require_case, require_team_user
from app.omega.router import case_view, enabled
from app.omega.schemas import TemplateStart
from app.omega.templates import PRESETS, seed_templates, setup_summary, start_template

router = APIRouter(prefix="/api/omega", tags=["omega"], dependencies=[Depends(enabled)])


@router.post("/materials/extract")
async def extract_meeting_material(file: UploadFile = File(...),
                                   user: User = Depends(get_current_user)):
    require_team_user(user)
    return extract_material(file.filename or "", await file.read(MAX_UPLOAD_BYTES + 1))


@router.get("/templates")
def list_templates(user: Annotated[User, Depends(get_current_user)],
                   db: Annotated[Session, Depends(get_session)]):
    team = require_team_user(user)
    seed_templates(db, user)
    rows = db.exec(select(OmegaCase).where(OmegaCase.team_key == team, OmegaCase.kind == "template",
                  OmegaCase.current_version > 0, OmegaCase.confirmed_revision == OmegaCase.revision)
                  .order_by(OmegaCase.created_at, OmegaCase.id)).all()
    preset_by_id = {str(uuid5(NAMESPACE_URL, f"omega-preset:{team}:{preset['title']}")): preset
                    for preset in PRESETS}
    result = []
    for row in rows:
        try:
            require_case(user, db, row)
        except HTTPException:
            continue
        editable = row.owner_id == user.id or user.role in {"manager", "admin"}
        snapshot = json.loads(row.draft_json)
        version = db.exec(select(OmegaCaseVersion).where(OmegaCaseVersion.case_id == row.id,
                          OmegaCaseVersion.version == row.current_version)).one()
        preset = preset_by_id.get(row.id, {}) if row.owner_id == 0 else {}
        result.append({**case_view(row), **setup_summary(snapshot, editable=editable), "case_version_id": version.id,
                       "card_group": preset.get("group", "drill" if row.owner_id == 0 else "other"),
                       "material_hint": preset.get("material_hint", "本次会议可上传资料或命题，仅用于本场练习"),
                       "suggested_topics": preset.get("topics", []),
                       "available_usages": ["training", "rehearsal", "real_review"] if row.owner_id == 0
                       else [snapshot.get("usage", "rehearsal")]})
    preset_order = {str(uuid5(NAMESPACE_URL, f"omega-preset:{team}:{preset['title']}")): index
                    for index, preset in enumerate(PRESETS)}
    result.sort(key=lambda item: preset_order.get(item["id"], len(PRESETS)) if item["owner_id"] == 0
                else len(PRESETS))
    return result


@router.post("/template-starts", status_code=201)
def template_start(body: TemplateStart, response: Response,
                   user: Annotated[User, Depends(get_current_user)],
                   db: Annotated[Session, Depends(get_session)]):
    result, created = start_template(db, user, body)
    response.status_code = 201 if created else 200
    return result
