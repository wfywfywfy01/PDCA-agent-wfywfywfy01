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
    {"title": "新人：30秒介绍价值", "meeting_type": "introduction",
     "stage": "模拟首次见面，对方只愿给很短时间了解是否值得继续谈。",
     "brief": "模拟代理首次听销售介绍；公司和产品的具体资料须由销售依据已核实信息说明。",
     "stance": "你是代理负责人。对泛泛介绍没有耐心；销售若不能说明与你业务相关的可核实价值，就不安排后续。",
     "objection": "先说清楚对我的门店有什么实际价值，否则没必要继续。",
     "goal": "说明可核实的相关价值，问出对方最关心的问题，并争取具体的后续沟通。",
     "minimum": "让对方说出一个关注点，并确认是否愿意继续了解。"},
    {"title": "初访：对方没时间", "meeting_type": "introduction",
     "stage": "模拟首次联系代理；尚未确认采购计划与决策角色。",
     "brief": "模拟第一次联系代理；目前合作状况、采购计划和选品负责人均未知。",
     "stance": "你正在处理其他事务。销售若长篇推介，你会说没时间；只有具体相关的问题才值得约下次沟通。",
     "objection": "我现在没时间，先发资料吧。",
     "goal": "确认对方角色和一个业务关注点，并争取可执行的下次沟通安排。",
     "minimum": "确认资料需要回答什么问题，以及对方是否接受后续联系。"},
    {"title": "需求：已有合作品牌", "meeting_type": "discovery",
     "stage": "模拟代理已与其他品牌合作；是否愿意增加品牌尚未确认。",
     "brief": "代理已有合作品牌；具体品牌、销量及条款均未知。",
     "stance": "你担心新品牌占用门店资源。要求销售先理解现有合作的不足，再谈引入理由。",
     "objection": "我们已经有合作品牌，再加一个有什么必要？",
     "goal": "问清现有合作中未解决的需求、决策角色及一个可核实的评估动作。",
     "minimum": "明确一个值得共同验证的业务问题。"},
    {"title": "首单：担心压库存", "meeting_type": "negotiation",
     "stage": "模拟谈到首批订单，但代理尚未接受库存风险。",
     "brief": "双方讨论试单；订单量、周转数据、退换货政策和授权条件均未知。",
     "stance": "你担心货卖不动。要求销售说明如何评估风险；若对方保证退货，追问书面授权。",
     "objection": "首批货压在店里卖不动怎么办？",
     "goal": "识别库存风险的判断口径，争取可核实的试单评估下一步。",
     "minimum": "确认一个影响首单决定的库存条件和负责核对的人。"},
    {"title": "拿单：先要降价", "meeting_type": "order",
     "stage": "模拟已谈到下单条件；代理提出先降价，具体报价与授权未知。",
     "brief": "双方讨论首单；报价、折扣权限、付款和交付条件均未知。",
     "stance": "你关注利润空间，要求销售先降价才继续谈；若对方答应，追问批准人和交换条件。",
     "objection": "你先降价，我才考虑下单。",
     "goal": "问清降价诉求的依据，在授权边界内争取可核实的订单条件核对。",
     "minimum": "确认价格判断依据和下一步核对的负责人。"},
    {"title": "新人上手", "meeting_type": "introduction", "goal": "清楚介绍价值，确认客户最关心的问题和一个下一步。",
     "brief": "公司介绍和真实产品资料尚未提供，请先澄清，不能作未经核实的承诺。"},
    {"title": "首次触达", "meeting_type": "discovery", "goal": "问清需求、决策角色和下次沟通时间。",
     "brief": "模拟首次交流；客户需求和采购权限尚未确认。"},
    {"title": "首单谈判", "meeting_type": "negotiation", "goal": "澄清首单顾虑，争取明确的行动负责人和时间表。",
     "brief": "模拟首单讨论；价格、交期和商业授权尚未提供。"},
)


def seed_templates(db: Session, user: User) -> None:
    team = require_team_user(user)
    for preset in PRESETS:
        title = preset["title"]
        case_id = str(uuid5(NAMESPACE_URL, f"omega-preset:{team}:{title}"))
        if db.get(OmegaCase, case_id):
            continue
        objection = preset.get("objection", "")
        snapshot = CaseCreate(
            kind="template", title=title, usage="training", meeting_type=preset["meeting_type"],
            public_brief=preset.get("brief", f"模拟练习：{preset['goal']}"),
            counterparty_brief=preset.get("stance", preset["brief"]),
            buyer_name="模拟代理" if objection else "模拟买方",
            buyer_role="代理负责人" if objection else "待确认",
            buyer_objections=[objection] if objection else [],
            participants=[{"id": "lead", "name": "模拟代理", "role": "代理负责人",
                           "is_primary": True, "concerns": [objection], "known_facts": [],
                           "decision_authority": "决策权限待确认"}] if objection else [],
            stage_summary=preset.get("stage", "尚未开始；真实业务事实未提供"),
            goal={"outcome_type": "schedule", "success_condition": preset["goal"],
                  "ideal": "双方明确下一步、负责人和时间", "minimum": preset.get("minimum", "确认一个可执行的下一步"),
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
