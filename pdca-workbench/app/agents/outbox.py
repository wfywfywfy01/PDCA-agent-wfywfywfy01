# -*- coding: utf-8 -*-
"""Outbox：所有外发消息的唯一出口（第 12 节）。

规则：
- 同一幂等键只能有一条 Outbox（数据库唯一约束 + 预查双保险）。
- 高风险消息（扣罚/合同/折扣/规则变更/争议红黑榜/删除撤回）强制 manual_required，
  任何调用方传 auto_template 也会被强制升级。
- auto_template 只有在 PDCA_AGENT_AUTO_TEMPLATE_PUSH=1 时才允许直接进入待发送；
  否则统一进入 pending 等人工批准。
- 批准/拒绝/重试全部写入 audit_logs；发送失败重试一次，仍失败保留审计并可手动重试。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.audit import log_action
from app.config import get_settings
from app.database import get_engine
from app.agents.models import AgentOutbox
from app.vps_im_push import push_duzhan_message, push_vps_alert, push_vps_message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 这些内容永远需要人工批准，即使模板化发送已开启。
_FORCED_MANUAL_MARKERS = (
    "扣罚", "罚款", "合同", "折扣", "返点", "权益承诺", "规则变更", "红黑榜", "撤回", "删除", "更正",
)


def forced_manual(body: str, kind: str) -> bool:
    """高风险消息判定：命中敏感词或敏感类型时强制人工审批。"""
    risky_kinds = {"penalty", "contract", "discount", "rule_change", "board_dispute", "retract"}
    if kind in risky_kinds:
        return True
    return any(marker in body for marker in _FORCED_MANUAL_MARKERS)


def create_outbox(
    *,
    idempotency_key: str,
    channel_id: str,
    body: str,
    message_kind: str = "group_followup",
    approval_policy: str = "manual_required",
    run_id: int | None = None,
    task_id: int | None = None,
    evidence: list[dict] | None = None,
) -> AgentOutbox | None:
    """创建 Outbox 记录；同幂等键已存在时返回 None（调用方视为已处理）。

    approval_policy 只接受 auto_template / manual_required / manual_if_risky；
    manual_if_risky 会在内容命中高风险特征时升级为 manual_required。
    auto_template 需 PDCA_AGENT_AUTO_TEMPLATE_PUSH=1 才直接进入 approved(auto)，
    否则保持 pending。
    """
    policy = approval_policy if approval_policy in (
        "auto_template", "manual_required", "manual_if_risky"
    ) else "manual_required"
    if forced_manual(body, message_kind):
        policy = "manual_required"
    elif policy == "manual_if_risky":
        policy = "manual_required"
    auto_push = get_settings().agent_auto_template_push
    approval_status = "approved" if (policy == "auto_template" and auto_push) else "pending"
    now = utcnow()
    with Session(get_engine()) as session:
        existing = session.exec(
            select(AgentOutbox).where(AgentOutbox.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            return None
        row = AgentOutbox(
            idempotency_key=idempotency_key[:160],
            run_id=run_id,
            task_id=task_id,
            channel_id=channel_id[:64],
            message_kind=message_kind[:32],
            body=body,
            evidence_json=json.dumps(evidence or [], ensure_ascii=False)[:65536],
            approval_policy=policy,
            approval_status=approval_status,
            approved_by="auto" if approval_status == "approved" else "",
            approved_at=now if approval_status == "approved" else None,
            send_status="pending",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        try:
            session.commit()
            session.refresh(row)
            return row
        except IntegrityError:
            session.rollback()
            return None


def _load(session: Session, outbox_id: int) -> AgentOutbox | None:
    return session.get(AgentOutbox, outbox_id)


def approve_outbox(outbox_id: int, username: str) -> dict:
    """人工批准；只有 pending 可批准。"""
    with Session(get_engine()) as session:
        row = _load(session, outbox_id)
        if row is None:
            return {"ok": False, "detail": "Outbox 不存在"}
        if row.approval_status != "pending":
            return {"ok": False, "detail": f"当前状态 {row.approval_status} 不可批准"}
        row.approval_status = "approved"
        row.approved_by = username[:128]
        row.approved_at = utcnow()
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        log_action(username, "agent_outbox.approve", f"outbox:{outbox_id}",
                   {"channel_id": row.channel_id, "kind": row.message_kind})
        return {"ok": True, "outbox_id": outbox_id, "approval_status": "approved"}


def reject_outbox(outbox_id: int, username: str, reason: str = "") -> dict:
    """人工拒绝；只有 pending 可拒绝，内容保留审计。"""
    with Session(get_engine()) as session:
        row = _load(session, outbox_id)
        if row is None:
            return {"ok": False, "detail": "Outbox 不存在"}
        if row.approval_status != "pending":
            return {"ok": False, "detail": f"当前状态 {row.approval_status} 不可拒绝"}
        row.approval_status = "rejected"
        row.approved_by = username[:128]
        row.approved_at = utcnow()
        row.last_error = (reason or "")[:2000]
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        log_action(username, "agent_outbox.reject", f"outbox:{outbox_id}",
                   {"channel_id": row.channel_id, "reason": reason[:200]})
        return {"ok": True, "outbox_id": outbox_id, "approval_status": "rejected"}


def retry_outbox(outbox_id: int, username: str) -> dict:
    """发送失败或已拒绝后可重新进入 pending（需再次批准/模板授权）。"""
    with Session(get_engine()) as session:
        row = _load(session, outbox_id)
        if row is None:
            return {"ok": False, "detail": "Outbox 不存在"}
        if row.approval_status not in ("rejected", "approved") or row.send_status != "failed":
            if row.send_status != "failed":
                return {"ok": False, "detail": "只有发送失败（或已拒绝）的记录可重试"}
        row.approval_status = "pending" if row.approval_policy != "auto_template" else "approved"
        if row.approval_status == "approved":
            row.approved_by = "retry:" + username[:120]
            row.approved_at = utcnow()
        row.send_status = "pending"
        row.last_error = ""
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        log_action(username, "agent_outbox.retry", f"outbox:{outbox_id}")
        return {"ok": True, "outbox_id": outbox_id, "approval_status": row.approval_status}


def _deliver(row: AgentOutbox) -> bool:
    """按消息类型选择通道发送；失败返回 False。"""
    if row.message_kind == "alert":
        return push_vps_alert(row.body)
    if row.message_kind in ("daily_brief", "daily_report"):
        return push_vps_message(row.body)
    return push_duzhan_message(row.body, row.channel_id, idempotency_key=row.idempotency_key)


def send_due(limit: int = 40) -> dict:
    """发送已批准且未发送的消息；单条失败重试一次，仍失败标记 failed 并告警。"""
    settings = get_settings()
    if not settings.agent_outbox_enabled:
        return {"ok": True, "sent": 0, "failed": 0, "skipped": "outbox 发送未启用"}
    sent = 0
    failed = 0
    with Session(get_engine()) as session:
        rows = session.exec(
            select(AgentOutbox)
            .where(AgentOutbox.approval_status == "approved")
            .where(AgentOutbox.send_status.in_(["pending", "failed"]))
            .order_by(AgentOutbox.id)
            .limit(limit)
        ).all()
        for row in rows:
            if row.send_status == "sent":
                continue
            # 规格 8.4：推送失败最多重试一次；仍失败写 failed 并告警。
            ok = _deliver(row)
            row.send_attempts += 1
            row.updated_at = utcnow()
            if not ok and row.send_attempts < 2:
                ok = _deliver(row)
                row.send_attempts += 1
                row.updated_at = utcnow()
            if ok:
                row.send_status = "sent"
                row.sent_at = utcnow()
                row.last_error = ""
                sent += 1
                log_action("system", "agent_outbox.sent", f"outbox:{row.id}",
                           {"channel_id": row.channel_id, "kind": row.message_kind})
            elif row.send_attempts >= 2:
                row.send_status = "failed"
                row.last_error = "两次发送均失败"
                failed += 1
                from app.alerting import notify

                notify("Agent Outbox 发送失败", f"outbox:{row.id} channel={row.channel_id}")
        session.commit()
    return {"ok": True, "sent": sent, "failed": failed}


def list_outbox(
    *,
    approval_status: str = "",
    limit: int = 100,
) -> list[dict]:
    """后台审批列表（倒序）。"""
    with Session(get_engine()) as session:
        statement = select(AgentOutbox).order_by(AgentOutbox.id.desc()).limit(min(limit, 300))
        if approval_status:
            statement = statement.where(AgentOutbox.approval_status == approval_status)
        rows = session.exec(statement).all()
        return [
            {
                "id": row.id,
                "idempotency_key": row.idempotency_key,
                "run_id": row.run_id,
                "task_id": row.task_id,
                "channel_id": row.channel_id,
                "message_kind": row.message_kind,
                "body_preview": row.body[:300],
                "approval_policy": row.approval_policy,
                "approval_status": row.approval_status,
                "approved_by": row.approved_by,
                "send_status": row.send_status,
                "send_attempts": row.send_attempts,
                "last_error": row.last_error[:300],
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            }
            for row in rows
        ]
