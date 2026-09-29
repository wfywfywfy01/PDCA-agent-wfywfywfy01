"""Team and source access checked at every read or write."""
from __future__ import annotations

from uuid import UUID
import json

from fastapi import HTTPException
from sqlmodel import Session

from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope
from app.knowledge.client import require_knowledge_access


def require_team_user(user: User) -> str:
    team = (user.team_key or "").strip()
    if user.role not in {"sales", "manager", "admin"} or not team or user.id is None:
        raise HTTPException(403, "Omega 需要有效的销售团队身份")
    return team


def require_case(user: User, session: Session, case) -> None:
    if case is None or case.team_key != require_team_user(user):
        raise HTTPException(404, "谈判任务不存在")
    if case.dealer_id:
        try:
            dealer_id = UUID(case.dealer_id)
        except ValueError:
            raise HTTPException(403, "客户资料标识无效") from None
        require_knowledge_access(user, session, dealer_id)


def require_writer(user: User, owner_id: int) -> None:
    if user.id != owner_id and user.role not in {"manager", "admin"}:
        raise HTTPException(403, "仅创建者或同组主管可以修改")


def require_session_source(user: User, session: Session, game, _seen: set[str] | None = None) -> None:
    _seen = _seen or set()
    if game.id in _seen:
        raise HTTPException(404, "会议来源链无效")
    _seen.add(game.id)
    if game.assignment_id:
        from app.omega.models import OmegaAssignment, OmegaReport, OmegaSession
        assignment = session.get(OmegaAssignment, game.assignment_id)
        report = session.get(OmegaReport, assignment.source_report_id) if assignment and assignment.source_report_id else None
        source = session.get(OmegaSession, report.session_id) if report else None
        if assignment and assignment.source_report_id and source is None:
            raise HTTPException(404, "会议来源已失效")
        if source:
            require_session_source(user, session, source, _seen)
    if game.mode != "real_review":
        return
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return
    allowed = {normalize_scope_key(value) for value in scope.owner_keys}
    source_keys = set(json.loads(game.source_access_keys_json))
    if not allowed.intersection(source_keys):
        raise HTTPException(404, "会议复盘不存在或来源权限已失效")
