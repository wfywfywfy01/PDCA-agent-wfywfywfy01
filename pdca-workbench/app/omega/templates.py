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
from app.omega.reports import weights_for_meeting
from app.omega.router import canonical, digest
from app.omega.schemas import CaseCreate, TemplateStart


MEETING_PRESETS = (
    {"title": "破冰会议", "meeting_type": "introduction", "group": "cooperation",
     "topics": ["品牌与产品", "当地市场划分", "客户与公司背景", "需求与痛点"],
     "material_hint": "品牌介绍、产品目录、当地市场资料、客户公开背景",
     "stage": "首次正式交流；客户背景、当地市场打法和合作意愿尚待核实。",
     "brief": "介绍已核实的品牌、产品和市场扩张方向；通过提问了解代理背景、当地市场分层、机会、痒点与痛点。",
     "stance": "你是当地代理负责人。愿意互相了解，但不会因泛泛介绍透露业务细节；销售先说明相关性再谈合作。",
     "objection": "你们的品牌在我们市场适合哪些客户？先别急着推产品。",
     "goal": "讲清已核实的价值，问出客户背景、市场打法和至少一个真实需求，并约定下一次沟通。",
     "minimum": "确认客户角色、一个优先问题和下一步资料或会议安排。"},
    {"title": "方案推进会议", "meeting_type": "proposal", "group": "cooperation",
     "topics": ["客户利润机会", "解决当前痛点", "提升品牌定位", "方案验证"],
     "material_hint": "首次会议纪要、客户问题清单、经核实的产品与市场资料",
     "stage": "已完成首次了解；客户关注点需要转成可核对的合作方案。",
     "brief": "依据上一轮确认的客户痒点、痛点和定位诉求提出方案；未知销量、利润与投入不得猜测。",
     "stance": "你是代理负责人。只接受针对自身业务问题的方案；要求说明赚钱路径、品牌定位收益及需要共同验证的假设。",
     "objection": "这套方案如何帮我赚钱、又怎样提升我现有品牌的定位？",
     "goal": "把客户问题对应到可核实的方案、收益判断口径和下一步试点或决策动作。",
     "minimum": "确认一个客户认可的问题、一个待验证假设及负责核对的人。"},
    {"title": "试订单推进", "meeting_type": "order", "group": "cooperation",
     "topics": ["政策与折扣", "市场营销", "售后政策", "开店支持", "交期与物流"],
     "material_hint": "经批准的价格/折扣、售后、交货、物流、开店和营销政策版本",
     "stage": "客户有试单意向，尚未确认政策边界和订单条件。",
     "brief": "逐项核对试单所需政策、折扣、营销支持、售后、开店、交货和物流安排；未获批条款不得承诺。",
     "stance": "你是代理采购负责人。会问具体折扣、支持、售后责任、交期和物流时间；口头保证不能代替书面政策。",
     "objection": "这些政策能写进试单条件吗？先给我明确的交付和售后边界。",
     "goal": "列清试单待确认条件、书面依据、双方负责人和决定时间，不越权承诺。",
     "minimum": "确认阻碍试单的首要条件及其核对负责人。"},
    {"title": "合作启动培训", "meeting_type": "enablement", "group": "training",
     "topics": ["品牌与文化", "产品培训", "工具使用", "销售技巧", "店铺陈列", "产品铺货"],
     "material_hint": "本次选定主题的正式课件、产品手册、工具说明或陈列标准",
     "stage": "客户已购产品，团队需要按真实资料完成上手培训。",
     "brief": "按本次命题培训品牌、文化、产品、工具、销售、陈列或铺货；没有资料的细节先核对，不假设员工已掌握。",
     "stance": "你是代理店铺新员工。会追问具体操作并尝试复述；讲得太抽象时要求现场示范或可核对资料。",
     "actor_name": "模拟店员", "actor_role": "代理店铺新员工",
     "objection": "我听懂概念了，但到店里该怎么做？能用一个实际例子教我吗？",
     "goal": "围绕本次主题完成讲解、示范、学员复述和下一步练习安排。",
     "minimum": "让学员准确复述一个关键做法，指出一个仍需补充的资料或练习。"},
    {"title": "终销培训", "meeting_type": "retail_training", "group": "training",
     "topics": ["终销对话", "门店五件套", "社媒获客", "跟进与转化"],
     "material_hint": "公司正式的门店五件套定义、终销案例、社媒素材与渠道规范",
     "stage": "产品已进入门店；店员需要把培训转成实际终销动作。",
     "brief": "训练需求发现、产品演示、异议回应、门店五件套和社媒引流；五件套具体内容以上传的公司版本为准。",
     "stance": "你是门店销售。会提出真实顾客异议，要求示范从接待到下一步跟进的完整动作。",
     "actor_name": "模拟门店销售", "actor_role": "代理门店销售",
     "objection": "顾客看完就走，社媒来的线索也不回复，我该怎么跟进？",
     "goal": "让门店销售演练一段终销对话，明确五件套/社媒的实际用法与可检查动作。",
     "minimum": "完成一次具体角色演练，并约定一个可检查的门店执行动作。"},
    {"title": "市场营销支持会议", "meeting_type": "marketing_support", "group": "operation",
     "topics": ["活动目标", "本地渠道", "物料与预算", "审批分工", "效果复盘"],
     "material_hint": "活动方案、当地渠道数据、品牌素材规范、已获批预算与排期",
     "stage": "双方讨论市场支持，目标、投入和责任边界尚需确认。",
     "brief": "围绕当地市场目标讨论活动、素材、渠道、预算、审批和效果评估；不把申请当成已批准支持。",
     "stance": "你是代理市场负责人。要求解释支持如何带来门店客流和终销，谁出资源、谁审批、怎么衡量。",
     "objection": "你们说会支持市场，具体给什么、何时到位、怎样判断有效？",
     "goal": "形成可核对的营销试点计划：目标、资料/资源、责任人、审批点和复盘指标。",
     "minimum": "确认一个本地营销目标和双方待核对的资源清单。"},
    {"title": "新品培训", "meeting_type": "product_launch", "group": "training",
     "topics": ["新品定位", "与旧品差异", "演示与话术", "常见问答", "上市准备"],
     "material_hint": "正式新品手册、发布日期与供货信息、价格政策、演示素材",
     "stage": "新品即将或已经提供培训资料；门店需要掌握适用客群和差异。",
     "brief": "依据正式资料培训新品定位、卖点、与旧品差异、演示、FAQ 和供货边界；未知参数不能编造。",
     "stance": "你是代理销售主管。会要求准确对比旧品和新品，并用顾客问题检查讲师是否说得清。",
     "actor_name": "模拟销售主管", "actor_role": "代理销售主管",
     "objection": "除了新，顾客为什么选这款？和现有产品的差别是什么？",
     "goal": "让参会者讲清目标客群、可核实差异、一个演示动作和待核对问题。",
     "minimum": "准确说出一个可核实差异，并确认未掌握信息的核对路径。"},
    {"title": "店铺周会", "meeting_type": "store_weekly", "group": "operation",
     "topics": ["本周终销", "库存与缺货", "客流转化", "跟进动作"],
     "material_hint": "本周终销、库存、线索和门店执行数据；缺失指标标记待核对",
     "stage": "每周经营复盘；终销、库存和门店执行差异需要定位。",
     "brief": "用已提供的数据看本周终销、库存、客流转化和店铺表现；无数据时先确认口径与缺口。",
     "stance": "你是店长。会质疑没有数据依据的结论，并要求只确定本周能落实的少数动作。",
     "actor_name": "模拟店长", "actor_role": "代理店长",
     "objection": "销量没起来，你说的原因有数据吗？下周具体改哪一件事？",
     "goal": "基于可核对数据找到一个主要问题，定下责任人、动作和下周检查点。",
     "minimum": "确认一个数据缺口或经营问题，以及一项可检查动作。"},
    {"title": "店铺月会", "meeting_type": "store_monthly", "group": "operation",
     "topics": ["月度终销", "库存结构", "门店表现", "下月计划"],
     "material_hint": "月度终销、库存周转、活动与门店表现数据及上月行动结果",
     "stage": "月度经营复盘；需要区分短期波动与持续问题。",
     "brief": "复盘月度终销、库存结构、门店与营销表现，对照上月动作制定下月计划。",
     "stance": "你是代理运营负责人。要求比较趋势和不同门店，追问行动结果与资源投入依据。",
     "actor_name": "模拟运营负责人", "actor_role": "代理运营负责人",
     "objection": "你建议加资源，先说清哪些店有效，哪些库存需要处理。",
     "goal": "形成基于数据的月度问题判断、资源取舍和下月负责人/时间表。",
     "minimum": "确认一个可核实的月度问题和下一步分析负责人。"},
    {"title": "开店准备会议", "meeting_type": "store_opening", "group": "operation",
     "topics": ["选址与客群", "陈列与物料", "人员培训", "首批铺货", "开业节点"],
     "material_hint": "门店计划、选址/客群、陈列标准、铺货与培训清单",
     "stage": "合作进入开店准备，投入、标准和责任边界待确认。",
     "brief": "核对选址客群、陈列、培训、铺货、物料和开业计划，支持以已批准文件为准。",
     "stance": "你是代理运营负责人。会问开店前哪些条件必须到位，谁承担执行和风险。",
     "actor_name": "模拟运营负责人", "actor_role": "代理运营负责人",
     "objection": "如果物料或培训没到位，开业节点和责任怎么算？",
     "goal": "列出开店关键前置条件、缺口、双方负责人和可核对的里程碑。",
     "minimum": "确认一个阻碍开业的缺口和负责核对的人。"},
    {"title": "补货复购会议", "meeting_type": "reorder", "group": "operation",
     "topics": ["动销与库存", "补货结构", "交期与资金", "滞销处理"],
     "material_hint": "门店终销、在途/现货库存、交期和已批准补货政策",
     "stage": "已有销售和库存记录，双方评估是否补货及怎样控制风险。",
     "brief": "依据终销与库存数据讨论补货节奏、产品结构、资金和滞销风险；数据未知则先核对。",
     "stance": "你是代理采购负责人。会要求用动销证明补货需要，并担心再次形成压货。",
     "objection": "上批货还有库存，凭什么现在补？先看实际动销和周转。",
     "goal": "明确补货判断口径、待核对数据和条件性下一步，不凭空承诺销量。",
     "minimum": "确认一个补货判断数据和核对负责人。"},
    {"title": "售后问题协调会议", "meeting_type": "aftersales", "group": "operation",
     "topics": ["问题事实", "责任界面", "处理时限", "客户沟通", "复发预防"],
     "material_hint": "售后工单、产品信息、已批准服务政策和沟通记录",
     "stage": "出现售后或服务争议；事实、责任与处理路径需要共同核实。",
     "brief": "先核实问题和影响，再依据有效售后政策协调处理、升级和客户沟通。",
     "stance": "你是代理售后负责人。会追问处理责任、时限和顾客安抚方式；不接受未经核实的承诺。",
     "actor_name": "模拟售后负责人", "actor_role": "代理售后负责人",
     "objection": "顾客还在等回复，谁负责、什么时候给可核实的方案？",
     "goal": "形成问题事实、待核对政策、责任人、升级动作和明确回复时间。",
     "minimum": "确认下一次回复的负责人和时间，不擅自承诺赔付。"},
    {"title": "临时自定义会议", "meeting_type": "custom", "group": "other",
     "topics": ["本次要谈什么", "谁参加", "希望得到什么结果"],
     "material_hint": "可上传任意与本场命题相关的可读资料；请先写清本次会议命题",
     "stage": "临时会议；具体目的、参会人和背景由销售填写。",
     "brief": "临时会议的事实与命题尚未提供；先依据销售填写的背景和本次资料澄清。",
     "stance": "你是本场会议的主要参会方。对模糊目的会追问；只依据已给信息表达立场。",
     "actor_name": "模拟参会人", "actor_role": "主要参会方",
     "objection": "今天这场会要解决什么问题？先说清楚预期结果。",
     "goal": "明确本次会议命题、参会角色、需要解决的问题和可核对的下一步。",
     "minimum": "确认一项本场待解决问题和下一步负责人。"},
)


DRILL_PRESETS = (
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

PRESETS = MEETING_PRESETS + DRILL_PRESETS


def seed_templates(db: Session, user: User) -> None:
    team = require_team_user(user)
    for preset in PRESETS:
        title = preset["title"]
        case_id = str(uuid5(NAMESPACE_URL, f"omega-preset:{team}:{title}"))
        if db.get(OmegaCase, case_id):
            continue
        objection = preset.get("objection", "")
        actor_name = preset.get("actor_name", "模拟代理")
        actor_role = preset.get("actor_role", "代理负责人")
        snapshot = CaseCreate(
            kind="template", title=title, usage="training", meeting_type=preset["meeting_type"],
            public_brief=preset.get("brief", f"模拟练习：{preset['goal']}"),
            counterparty_brief=preset.get("stance", preset["brief"]),
            buyer_name=actor_name if objection else "模拟买方",
            buyer_role=actor_role if objection else "待确认",
            buyer_objections=[objection] if objection else [],
            score_weights=weights_for_meeting(preset["meeting_type"]),
            participants=[{"id": "lead", "name": actor_name, "role": actor_role,
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
    if not row.current_version:
        return {"case_id": row.id, "case_version_id": None, "session_id": None,
                "next_action": "review_case", "summary": setup_summary(json.loads(row.draft_json))}
    version = db.exec(select(OmegaCaseVersion).where(
        OmegaCaseVersion.case_id == row.id, OmegaCaseVersion.version == 1,
    )).one()
    snapshot = json.loads(version.snapshot_json)
    return {"case_id": row.id, "case_version_id": version.id, "session_id": row.initial_session_id,
            "next_action": "import_meeting" if snapshot.get("usage") == "real_review" else "practice",
            "summary": setup_summary(snapshot)}


def start_template(db: Session, user: User, body: TemplateStart) -> tuple[dict, bool]:
    team = require_team_user(user)
    request_hash = digest(body.model_dump(mode="json", exclude={"save_only"} if not body.save_only else set()))

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
    if body.dealer_id or (body.usage == "real_review" and template.owner_id == 0):
        # Seeded roleplay details are never facts about a real customer or meeting.
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
                    draft_json=canonical(snapshot), current_version=0 if body.save_only else 1,
                    confirmed_revision=0 if body.save_only else 1)
    require_case(user, db, row)
    try:
        db.add(row)
        db.flush()
        if not body.save_only:
            version = OmegaCaseVersion(case_id=row.id, version=1, snapshot_json=canonical(snapshot),
                                       content_hash=digest(snapshot), confirmed_by=user.id)
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
