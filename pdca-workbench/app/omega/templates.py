"""Team presets and one-transaction, idempotent personal launches."""
from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.models import User
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaSession
from app.omega.policy import require_case, require_team_user
from app.omega.router import canonical, digest
from app.omega.schemas import CaseCreate, TemplateStart


PRESETS = (
    ("新人上手", "introduction", "清楚介绍价值，确认客户最关心的问题和一个下一步。", "公司介绍和真实产品资料尚未提供，请先澄清，不能作未经核实的承诺。"),
    ("首次触达", "discovery", "问清需求、决策角色和下次沟通时间。", "模拟首次交流；客户需求和采购权限尚未确认。"),
    ("首单谈判", "negotiation", "澄清首单顾虑，争取明确的行动负责人和时间表。", "模拟首单讨论；价格、交期和商业授权尚未提供。"),
)


def seed_templates(db: Session, user: User) -> None:
    team = require_team_user(user)
    for title, meeting_type, goal, brief in PRESETS:
        case_id = str(uuid5(NAMESPACE_URL, f"omega-preset:{team}:{title}"))
        if db.get(OmegaCase, case_id):
            continue
        snapshot = CaseCreate(
            kind="template", title=title, usage="training", meeting_type=meeting_type,
            public_brief=f"模拟练习：{goal}", counterparty_brief=brief,
            buyer_name="模拟买方", buyer_role="待确认", stage_summary="尚未开始；真实业务事实未提供",
            goal={"outcome_type": "schedule", "success_condition": goal,
                  "ideal": "双方明确下一步、负责人和时间", "minimum": "确认一个可执行的下一步",
                  "hard_limits": ["不编造公司、产品、价格、交付及客户事实", "未经授权不得作商业承诺"]},
        ).model_dump(mode="json")
        row = OmegaCase(id=case_id, team_key=team, owner_id=0, title=title, kind="template",
                        draft_json=canonical(snapshot), current_version=1, confirmed_revision=1)
        version = OmegaCaseVersion(case_id=case_id, version=1, snapshot_json=canonical(snapshot),
                                   content_hash=digest(snapshot), confirmed_by=user.id)
        try:
            # A savepoint keeps another request's simultaneous seed harmless.
            with db.begin_nested():
                db.add(row)
                db.flush()
                db.add(version)
                db.flush()
        except IntegrityError:
            if db.get(OmegaCase, case_id) is None:
                raise
    db.commit()


def setup_summary(snapshot: dict, *, editable: bool = True) -> dict:
    return {"title": snapshot.get("title", ""), "stage": snapshot.get("stage_summary", ""),
            "goal": (snapshot.get("goal") or {}).get("success_condition", ""),
            "simulation": snapshot.get("usage", "rehearsal") != "real_review", "editable": editable}


def launch_view(db: Session, row: OmegaCase) -> dict:
    version = db.exec(select(OmegaCaseVersion).where(
        OmegaCaseVersion.case_id == row.id, OmegaCaseVersion.version == 1,
    )).one()
    snapshot = json.loads(version.snapshot_json)
    return {"case_id": row.id, "case_version_id": version.id, "session_id": row.initial_session_id,
            "next_action": "import_meeting" if snapshot.get("usage") == "real_review" else "practice",
            "summary": setup_summary(snapshot)}


def start_template(db: Session, user: User, body: TemplateStart) -> tuple[dict, bool]:
    team = require_team_user(user)
    request_hash = digest(body.model_dump(mode="json"))

    def replay() -> dict | None:
        row = db.exec(select(OmegaCase).where(OmegaCase.team_key == team,
            OmegaCase.owner_id == user.id, OmegaCase.launch_key == body.request_key)).first()
        if row is None:
            return None
        require_case(user, db, row)
        if row.launch_hash != request_hash:
            raise HTTPException(409, "请求编号已用于不同的启动内容")
        return launch_view(db, row)

    existing = replay()
    if existing is not None:
        return existing, False
    template = db.exec(select(OmegaCase).where(OmegaCase.id == body.template_id)
                       .with_for_update().execution_options(populate_existing=True)).first()
    require_case(user, db, template)
    if template.kind != "template":
        raise HTTPException(404, "预设不存在")
    if (template.current_version != body.template_version
            or template.confirmed_revision != template.revision):
        raise HTTPException(409, "预设已更新，请刷新后重试")
    source = db.exec(select(OmegaCaseVersion).where(OmegaCaseVersion.case_id == template.id,
                    OmegaCaseVersion.version == body.template_version)).one()
    snapshot = json.loads(source.snapshot_json)
    if body.dealer_id:
        # Templates describe simulated conditions, never facts about the selected real customer.
        snapshot.update(public_brief="已选择真实客户；尚未提供经核实的业务背景。",
                        counterparty_brief="客户的具体关注点和决策权限尚未确认。",
                        seller_private="", buyer_name="", buyer_role="", buyer_company="",
                        buyer_emotion="", buyer_objections=[], participants=[],
                        stage_summary="已选择真实客户；当前阶段尚未确认")
    snapshot.update(body.overrides)
    snapshot.update(kind="case", usage=body.usage, dealer_id=body.dealer_id,
                    opportunity_id=body.opportunity_id, source_template_version_id=source.id)
    try:
        validated = CaseCreate.model_validate(snapshot)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from None
    snapshot = validated.model_dump(mode="json")
    row = OmegaCase(team_key=team, owner_id=user.id, title=validated.title, dealer_id=validated.dealer_id,
                    kind="case", opportunity_id=validated.opportunity_id,
                    source_template_version_id=source.id, launch_key=body.request_key, launch_hash=request_hash,
                    draft_json=canonical(snapshot), current_version=1, confirmed_revision=1)
    require_case(user, db, row)
    version = OmegaCaseVersion(case_id=row.id, version=1, snapshot_json=canonical(snapshot),
                               content_hash=digest(snapshot), confirmed_by=user.id)
    try:
        db.add(row)
        db.flush()
        db.add(version)
        db.flush()
        if body.usage != "real_review":
            from app.omega.memory import create_context_snapshot
            context_json, source_ids_json = create_context_snapshot(db, user, row, snapshot)
            game = OmegaSession(case_id=row.id, case_version_id=version.id, team_key=team,
                                owner_id=user.id, mode=body.usage, context_snapshot_json=context_json,
                                context_source_session_ids_json=source_ids_json)
            db.add(game)
            row.initial_session_id = game.id
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = replay()
        if existing is not None:
            return existing, False
        raise HTTPException(409, "启动请求冲突，请刷新后重试") from None
    return launch_view(db, row), True
