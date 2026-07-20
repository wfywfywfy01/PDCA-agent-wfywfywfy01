# -*- coding: utf-8 -*-
"""Issue and consume one-time authorization-code style login tickets."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, update
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.scope import DataScope
from app.models.acquisition_login_ticket import AcquisitionLoginTicket

TICKET_TTL_SECONDS = 90


def issue_login_ticket(user: User, scope: DataScope, session: Session) -> str:
    """Create a short-lived code containing only the caller's scoped identity."""
    now = datetime.utcnow()
    session.exec(
        delete(AcquisitionLoginTicket).where(
            AcquisitionLoginTicket.expires_at < now - timedelta(days=1)
        )
    )
    code = secrets.token_urlsafe(32)
    ticket = AcquisitionLoginTicket(
        token_digest=_digest(code),
        user_id=int(user.id or 0),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        data_scope=scope.mode,
        owner_key=str(getattr(user, "owner_key", "") or ""),
        team_key=scope.team_key,
        owner_keys_json=json.dumps(list(scope.owner_keys), ensure_ascii=False),
        expires_at=now + timedelta(seconds=TICKET_TTL_SECONDS),
    )
    session.add(ticket)
    session.commit()
    return code


def consume_login_ticket(code: str, session: Session) -> dict:
    """Atomically consume a code so replayed or expired tickets fail closed."""
    normalized = str(code or "").strip()
    if not 32 <= len(normalized) <= 256:
        raise _invalid_ticket()
    now = datetime.utcnow()
    ticket = session.exec(
        select(AcquisitionLoginTicket).where(
            AcquisitionLoginTicket.token_digest == _digest(normalized),
            AcquisitionLoginTicket.consumed_at == None,  # noqa: E711
            AcquisitionLoginTicket.expires_at > now,
        )
    ).first()
    if not ticket or not ticket.user_id:
        raise _invalid_ticket()
    current_user = session.get(User, ticket.user_id)
    if (
        not current_user
        or not current_user.is_active
        or current_user.username != ticket.username
        or current_user.role != ticket.role
    ):
        raise _invalid_ticket()
    claimed = session.exec(
        update(AcquisitionLoginTicket)
        .where(
            AcquisitionLoginTicket.id == ticket.id,
            AcquisitionLoginTicket.consumed_at == None,  # noqa: E711
            AcquisitionLoginTicket.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if claimed.rowcount != 1:
        session.rollback()
        raise _invalid_ticket()
    session.commit()
    try:
        owner_keys = json.loads(ticket.owner_keys_json or "[]")
    except (TypeError, ValueError):
        owner_keys = []
    if not isinstance(owner_keys, list):
        owner_keys = []
    return {
        "subject": f"pdca:{ticket.user_id}",
        "username": ticket.username,
        "display_name": ticket.display_name,
        "role": ticket.role,
        "data_scope": ticket.data_scope,
        "owner_key": ticket.owner_key,
        "team_key": ticket.team_key,
        "owner_keys": [str(value) for value in owner_keys if str(value).strip()],
    }


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _invalid_ticket() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录票据无效或已过期，请从 PDCA 重新打开客户管理",
    )
