"""Scoped, transactional customer facts; no outbound calls or background collection."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope
from .models import (LifecycleAudit, LifecycleBusinessLink, LifecycleCustomer,
                     LifecycleEvidence, LifecycleIdentity, LifecycleProposal, uid, utcnow)

STAGES = {"pending": "待核", "lead": "线索", "contacted": "接洽", "intent": "意向",
          "qualified": "合格商机", "ordered": "订单", "paid": "回款", "paused": "暂停", "closed": "关闭"}
RANK = {stage: index for index, stage in enumerate(list(STAGES)[:7])}


def fail(code, message):
    raise HTTPException(code, message)


def aware(value):
    # SQLite drops timezone metadata; all persisted values entered through UTC validation.
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def dump(row):
    data = row.model_dump()
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = aware(value).isoformat()
        elif isinstance(value, Decimal):
            data[key] = format(value, "f")
    return data


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def actor(db: Session, supplied: User, *, write=False, finance=False):
    user = db.exec(select(User).where(User.id == supplied.id).execution_options(populate_existing=True)).first()
    if not user or not user.is_active or user.role not in {"viewer", "sales", "manager", "admin"}:
        fail(403, "当前身份无效")
    if write and user.role not in {"sales", "manager", "admin"}:
        fail(403, "需要销售或管理权限")
    if finance and user.role not in {"manager", "admin"}:
        fail(403, "财务关联核验需要管理权限")
    scope = resolve_data_scope(user, db)
    if scope.mode == "none" or (scope.mode == "team" and not scope.team_key):
        fail(403, "未配置客户数据权限")
    return user, scope


def allowed(scope, user, row):
    if scope.unrestricted:
        return True
    if scope.mode == "self":
        return (row.owner_user_id == user.id and bool(user.team_key)
                and normalize_scope_key(row.team_key) == normalize_scope_key(user.team_key))
    return scope.mode == "team" and bool(scope.team_key) and normalize_scope_key(row.team_key) == normalize_scope_key(scope.team_key)


def customer(db, user, customer_id, *, write=False, finance=False):
    user, scope = actor(db, user, write=write, finance=finance)
    row = db.exec(select(LifecycleCustomer).where(LifecycleCustomer.id == customer_id)
                  .with_for_update().execution_options(populate_existing=True)).first()
    if not row or not allowed(scope, user, row):
        fail(404, "客户不存在或无访问权")
    return row, user, scope


def owner(db, user, scope, owner_id):
    row = db.get(User, owner_id)
    if not row or not row.is_active or row.role not in {"sales", "manager", "admin"} or not row.team_key.strip():
        fail(422, "负责人必须是已配置团队的有效业务用户")
    if not scope.unrestricted:
        if scope.mode == "self" and row.id != user.id:
            fail(403, "只能为自己创建或管理客户")
        if scope.mode == "team" and normalize_scope_key(row.team_key) != normalize_scope_key(scope.team_key):
            fail(403, "负责人不在当前团队范围")
    return row


def customer_view(db, row):
    data = dump(row)
    data["assisted_routes"] = json.loads(data.pop("assisted_routes_json"))
    person = db.get(User, row.owner_user_id)
    data["owner_name"] = (person.display_name or person.username) if person else ""
    return data


def proposal_view(row):
    data = dump(row)
    data["changes"] = json.loads(data.pop("changes_json"))
    return data


def detail(db, user, customer_id):
    row, user, _ = customer(db, user, customer_id)
    result = {"customer": customer_view(db, row), "permissions": {
        "can_write": user.role in {"sales", "manager", "admin"},
        "can_verify_finance": user.role in {"manager", "admin"}},
        "live_collection": False}
    for name, model in [("identities", LifecycleIdentity), ("evidence", LifecycleEvidence),
                        ("proposals", LifecycleProposal), ("business_links", LifecycleBusinessLink),
                        ("audit", LifecycleAudit)]:
        rows = db.exec(select(model).where(model.customer_id == row.id)).all()
        result[name] = [proposal_view(item) if name == "proposals" else dump(item) for item in rows]
    return result


def audit(db, row, user, action, payload, request_key=None):
    item = LifecycleAudit(customer_id=row.id, actor_user_id=user.id, action=action,
                          request_key=request_key or uid(), payload_hash=digest(payload), payload_json=canonical(payload))
    db.add(item)


def replay(db, row, user, action, body, key):
    previous = db.exec(select(LifecycleAudit).where(LifecycleAudit.customer_id == row.id,
                                                   LifecycleAudit.request_key == key)).first()
    if previous:
        if previous.actor_user_id != user.id or previous.action != action or previous.payload_hash != digest(body):
            fail(409, "请求标识已用于不同操作")
        return True
    return False


def cas(db, row, expected_version, values):
    if row.version != expected_version:
        fail(409, "客户版本已变化，请刷新后重新确认")
    result = db.exec(update(LifecycleCustomer).where(LifecycleCustomer.id == row.id,
                    LifecycleCustomer.version == expected_version).values(
                        **values, version=expected_version + 1, updated_at=utcnow())
                    .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        fail(409, "客户版本已变化，请刷新后重新确认")


def check_qualified(values):
    if not values.get("entity_verified") or not all(values.get(key) for key in
            ("name", "decision_maker", "need", "next_action", "due_at")):
        fail(422, "合格商机需核实主体、决策人、需求、下一步动作及明确时间")


def checked_facts(values):
    for key, value in values.items():
        if value is None and key not in {"due_at", "route"}:
            fail(422, f"{key} 不能为 null")
    return values


def routes(primary, assisted):
    if any(isinstance(value, bool) or value not in range(1, 8) for value in assisted):
        fail(422, "协同路径须为1至7")
    if primary in assisted:
        fail(422, "协同路径不得重复主来源")
    return canonical(sorted(set(assisted)))


def check_attribution(primary, assisted, note):
    if (primary is not None or assisted) and not note.strip():
        fail(422, "人工分配主来源或协同路径时，须填写来源归属依据")


def create_customer(db, user, body):
    user, scope = actor(db, user, write=True)
    assigned = owner(db, user, scope, body.owner_user_id)
    check_attribution(body.route, body.assisted_routes, body.source_note)
    values = body.model_dump(exclude={"assisted_routes"})
    row = LifecycleCustomer(**values, assisted_routes_json=routes(body.route, body.assisted_routes), team_key=assigned.team_key)
    db.add(row)
    db.flush()
    audit(db, row, user, "created", body.model_dump(mode="json"))
    return row


def patch_customer(db, user, customer_id, body):
    row, user, scope = customer(db, user, customer_id, write=True)
    values = checked_facts(body.model_dump(exclude_unset=True, exclude={"expected_version"}))
    if "route" in values or "assisted_routes" in values:
        values["assisted_routes_json"] = routes(values.get("route", row.route),
            values.pop("assisted_routes", json.loads(row.assisted_routes_json)))
    check_attribution(values.get("route", row.route),
        json.loads(values.get("assisted_routes_json", row.assisted_routes_json)),
        values.get("source_note", row.source_note))
    if "owner_user_id" in values:
        assigned = owner(db, user, scope, values["owner_user_id"])
        values["team_key"] = assigned.team_key
    if RANK.get(row.highest_stage, 0) >= RANK["qualified"]:
        check_qualified({**row.model_dump(), **values})
    if RANK.get(row.highest_stage, 0) >= RANK["lead"] and not values.get("entity_verified", row.entity_verified):
        fail(422, "业务阶段客户必须保留主体核验；资料更正需先单独审核")
    before = {key: dump(row).get(key) for key in values}
    cas(db, row, body.expected_version, values)
    audit(db, row, user, "updated", {"before": before, "after": values, "version": body.expected_version + 1})


def add_identity(db, user, customer_id, body):
    row, user, _ = customer(db, user, customer_id, write=True)
    old = db.exec(select(LifecycleIdentity).where(LifecycleIdentity.namespace == body.namespace,
                                                LifecycleIdentity.external_id == body.external_id)).first()
    if old:
        if old.customer_id != row.id:
            fail(409, "该外部标识已绑定其他客户，不能自动合并或改绑")
        return old
    item = LifecycleIdentity(**body.model_dump(), customer_id=row.id, created_by=user.id)
    db.add(item)
    audit(db, row, user, "identity_added", body.model_dump())
    return item


def submit_proposal(db, user, customer_id, body):
    row, user, _ = customer(db, user, customer_id, write=True)
    if body.occurred_at > utcnow() + timedelta(minutes=5):
        fail(422, "业务事件时间不能在未来")
    identity = None
    if body.external_id:
        identity = db.exec(select(LifecycleIdentity).where(LifecycleIdentity.namespace == body.external_namespace,
                           LifecycleIdentity.external_id == body.external_id)).first()
        if not identity or identity.customer_id != row.id:
            fail(422, "外部客户标识未映射到此客户；不得按姓名猜配")
    payload = {"customer_id": row.id, **body.model_dump(mode="json")}
    old = db.exec(select(LifecycleEvidence).where(LifecycleEvidence.source_system == body.source_system,
                                                LifecycleEvidence.event_id == body.event_id)).first()
    if old:
        if old.customer_id != row.id or old.payload_hash != digest(payload):
            fail(409, "同一来源事件已登记不同内容")
        return db.exec(select(LifecycleProposal).where(LifecycleProposal.evidence_id == old.id)).one()
    source_message_key = None
    if body.source_system != "manual":
        source_message_key = digest([body.source_system,
            body.external_namespace if body.source_system == "ai_sales" else "",
            body.source_channel_id, body.source_message_id])
        if db.exec(select(LifecycleEvidence).where(LifecycleEvidence.source_message_key == source_message_key)).first():
            fail(409, "该原始消息已登记；更换事件ID不能重复导入")
    if body.business_link_id:
        link = db.get(LifecycleBusinessLink, body.business_link_id)
        if not link or link.customer_id != row.id:
            fail(422, "业务关联不属于此客户")
    changes = checked_facts(body.changes.model_dump(mode="json", exclude_unset=True))
    evidence = LifecycleEvidence(customer_id=row.id, source_system=body.source_system, event_id=body.event_id,
        source_channel_id=body.source_channel_id, source_message_id=body.source_message_id,
        source_message_key=source_message_key, identity_id=identity.id if identity else None,
        summary=body.summary, occurred_at=body.occurred_at,
        submitted_by=user.id, payload_hash=digest(payload))
    db.add(evidence)
    db.flush()
    proposal = LifecycleProposal(customer_id=row.id, evidence_id=evidence.id,
        proposed_stage=body.proposed_stage, changes_json=canonical(changes), business_link_id=body.business_link_id)
    db.add(proposal)
    audit(db, row, user, "proposal_submitted", {"proposal_id": proposal.id, "evidence_id": evidence.id})
    return proposal


def check_financial(db, row, proposal, occurred_at):
    link = db.get(LifecycleBusinessLink, proposal.business_link_id) if proposal.business_link_id else None
    kind = "payment" if proposal.proposed_stage == "paid" else "order"
    if not link or link.customer_id != row.id or link.kind != kind or link.status != "verified" or not link.verified_by:
        fail(422, "订单/回款阶段须关联独立核验的订单或收款记录，群消息不能替代")
    if aware(link.occurred_at) > occurred_at:
        fail(422, "阶段时间不得早于所关联业务凭证")
    if kind == "payment":
        order = db.get(LifecycleBusinessLink, link.order_link_id) if link.order_link_id else None
        if not order or order.customer_id != row.id or order.kind != "order" or order.status != "verified":
            fail(422, "收款必须关联同一客户已核验订单")


def review_proposal(db, user, customer_id, proposal_id, body, confirm):
    row, user, _ = customer(db, user, customer_id, write=True)
    action = "proposal_confirmed" if confirm else "proposal_rejected"
    payload = {"proposal_id": proposal_id, **body.model_dump(mode="json")}
    if replay(db, row, user, action, payload, body.request_key):
        return
    proposal = db.exec(select(LifecycleProposal).where(LifecycleProposal.id == proposal_id)
                       .with_for_update().execution_options(populate_existing=True)).first()
    if not proposal or proposal.customer_id != row.id:
        fail(404, "建议不存在或无访问权")
    if proposal.status != "pending":
        fail(409, "建议已处理")
    values = {}
    if confirm:
        evidence = db.get(LifecycleEvidence, proposal.evidence_id)
        if not evidence or evidence.customer_id != row.id:
            fail(422, "证据与客户不匹配")
        if evidence.identity_id:
            identity = db.get(LifecycleIdentity, evidence.identity_id)
            if not identity or identity.customer_id != row.id:
                fail(422, "证据身份映射已失效")
        occurred_at = aware(evidence.occurred_at)
        if row.last_stage_at and occurred_at < aware(row.last_stage_at):
            fail(409, "旧事件不能覆盖较新的客户阶段")
        target = proposal.proposed_stage
        if target in RANK and RANK[target] < RANK.get(row.highest_stage, 0):
            fail(409, "阶段不能倒退；暂停或关闭请明确记录")
        values = json.loads(proposal.changes_json)
        if values.get("due_at"):
            values["due_at"] = datetime.fromisoformat(values["due_at"])
        if target in RANK and RANK[target] >= RANK["lead"] and not values.get("entity_verified", row.entity_verified):
            fail(422, "未核实主体不能进入线索或后续业务阶段")
        if RANK.get(target, RANK.get(row.highest_stage, 0)) >= RANK["qualified"]:
            check_qualified({**row.model_dump(), **values})
        if target in {"ordered", "paid"}:
            check_financial(db, row, proposal, occurred_at)
        values.update(stage=target, last_stage_at=occurred_at)
        if target in RANK:
            values["highest_stage"] = target
    cas(db, row, body.expected_version, values)
    proposal.status = "confirmed" if confirm else "rejected"
    proposal.reviewed_by = user.id
    proposal.reviewed_at = utcnow()
    proposal.reason = body.reason
    db.add(proposal)
    audit(db, row, user, action, payload, body.request_key)


def submit_business_link(db, user, customer_id, body):
    row, user, _ = customer(db, user, customer_id, write=True)
    old = db.exec(select(LifecycleBusinessLink).where(LifecycleBusinessLink.kind == body.kind,
        LifecycleBusinessLink.namespace == body.namespace, LifecycleBusinessLink.external_id == body.external_id)).first()
    if old:
        fail(409, "业务凭证已登记，请查看原关联")
    if body.occurred_at > utcnow() + timedelta(minutes=5):
        fail(422, "业务凭证时间不能在未来")
    if body.kind == "payment":
        order = db.get(LifecycleBusinessLink, body.order_link_id) if body.order_link_id else None
        if not order or order.kind != "order" or order.customer_id != row.id or order.status != "verified":
            fail(422, "请先关联同一客户已核验订单")
        if order.currency != body.currency or aware(order.occurred_at) > body.occurred_at:
            fail(422, "收款币种或时间与订单不一致，需先核对原凭证")
    elif body.order_link_id:
        fail(422, "订单本身不能挂其他订单关联")
    link = LifecycleBusinessLink(**body.model_dump(), customer_id=row.id, submitted_by=user.id)
    db.add(link)
    audit(db, row, user, "business_link_submitted", {"link_id": link.id, **body.model_dump(mode="json")})
    return link


def verify_business_link(db, user, customer_id, link_id, body):
    row, user, _ = customer(db, user, customer_id, write=True, finance=True)
    payload = {"link_id": link_id, **body.model_dump()}
    if replay(db, row, user, "business_link_verified", payload, body.request_key):
        return
    link = db.exec(select(LifecycleBusinessLink).where(LifecycleBusinessLink.id == link_id)
                  .with_for_update().execution_options(populate_existing=True)).first()
    if not link or link.customer_id != row.id:
        fail(404, "业务关联不存在或无访问权")
    if link.status != "pending":
        fail(409, "业务关联已处理")
    result = db.exec(update(LifecycleBusinessLink).where(LifecycleBusinessLink.id == link.id,
        LifecycleBusinessLink.status == "pending").values(status="verified", verified_by=user.id,
            verified_at=utcnow(), verification_note=body.note).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        fail(409, "业务关联已被其他请求处理")
    audit(db, row, user, "business_link_verified", payload, body.request_key)
