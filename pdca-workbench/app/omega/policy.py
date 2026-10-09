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


def _require_context_scope(user: User, session: Session, dealer_id: str, opportunity_id: str | None) -> None:
    if dealer_id:
        try:
            parsed = UUID(dealer_id)
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(403, "客户资料标识无效") from None
        require_knowledge_access(user, session, parsed)
    if opportunity_id:
        from app.omega.memory import require_opportunity
        require_opportunity(user, session, opportunity_id, dealer_id=dealer_id)


def _require_frozen_scope(user: User, session: Session, version) -> None:
    if version is None:
        raise HTTPException(404, "冻结场景来源已失效")
    try:
        snapshot = json.loads(version.snapshot_json)
        if not isinstance(snapshot, dict):
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(404, "冻结场景来源无效") from None
    _require_context_scope(user, session, snapshot.get("dealer_id", ""), snapshot.get("opportunity_id"))


def require_case(user: User, session: Session, case, _seen: set[str] | None = None) -> None:
    if case is None or case.team_key != require_team_user(user):
        raise HTTPException(404, "谈判任务不存在")
    seen = set(_seen or ())
    if case.id in seen:
        raise HTTPException(404, "谈判任务来源链无效")
    seen.add(case.id)
    _require_context_scope(user, session, case.dealer_id, getattr(case, "opportunity_id", None))
    if getattr(case, "source_template_version_id", None):
        from app.omega.models import OmegaCase, OmegaCaseVersion
        version = session.get(OmegaCaseVersion, case.source_template_version_id)
        source = session.get(OmegaCase, version.case_id) if version else None
        require_case(user, session, source, seen)
        _require_frozen_scope(user, session, version)


def require_writer(user: User, owner_id: int) -> None:
    if user.id != owner_id and user.role not in {"manager", "admin"}:
        raise HTTPException(403, "仅创建者或同组主管可以修改")


def require_session_source(user: User, session: Session, game, _seen: set[str] | None = None) -> None:
    _seen = set(_seen or ())
    if game is None or game.team_key != require_team_user(user) or game.id in _seen:
        raise HTTPException(404, "会议来源链无效")
    _seen.add(game.id)
    from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaSession
    require_case(user, session, session.get(OmegaCase, game.case_id))
    _require_frozen_scope(user, session, session.get(OmegaCaseVersion, game.case_version_id))
    from app.omega.models import OmegaCaseVersion
    version = session.get(OmegaCaseVersion, game.case_version_id)
    if version is None:
        raise HTTPException(404, "场次上下文已失效")
    frozen = json.loads(getattr(game, "context_snapshot_json", "") or version.snapshot_json)
    if frozen.get("dealer_id"):
        try:
            require_knowledge_access(user, session, UUID(frozen["dealer_id"]))
        except (ValueError, HTTPException):
            raise HTTPException(404, "场次客户来源权限已失效") from None
    if frozen.get("opportunity_id"):
        from app.omega.memory import require_opportunity
        require_opportunity(user, session, frozen["opportunity_id"], dealer_id=frozen.get("dealer_id", ""))
    for source_id in json.loads(getattr(game, "context_source_session_ids_json", "[]")):
        source = session.get(OmegaSession, source_id)
        if source is None:
            raise HTTPException(404, "记忆来源已失效")
        require_session_source(user, session, source, _seen)
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
