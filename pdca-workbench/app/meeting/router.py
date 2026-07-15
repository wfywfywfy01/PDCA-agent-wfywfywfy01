# -*- coding: utf-8 -*-
"""会议中心 API 路由。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from app.auth.deps import require_role
from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope
from app.database import get_session
from app.legacy import bridge
from app.validation import require_iso_date
from sqlmodel import Session

router = APIRouter(tags=["meeting"])


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _meeting_summary(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "internal": sum(1 for row in rows if row.get("meeting_type") == "internal"),
        "external": sum(1 for row in rows if row.get("meeting_type") == "external"),
        "duration_minutes": round(sum(_number(row.get("duration_minutes")) for row in rows), 1),
        "todo_count": sum(len(row.get("todos") or []) for row in rows),
    }


def _meeting_counts(rows: list[dict]) -> dict:
    counts = {"total": len(rows), "interview": 0, "report": 0, "customer": 0}
    for row in rows:
        bucket = str(row.get("bucket") or "report")
        if bucket in counts and bucket != "total":
            counts[bucket] += 1
    return counts


def _meeting_matches(row: dict, allowed: set[str]) -> bool:
    values: list[str] = []
    for participant in row.get("participants") or []:
        if isinstance(participant, dict):
            values.extend(str(participant.get(key) or "") for key in ("name", "display_name", "login", "email"))
        else:
            values.append(str(participant or ""))
    for todo in row.get("todos") or []:
        if isinstance(todo, dict):
            values.extend(str(todo.get(key) or "") for key in ("owner", "assignee", "owner_name"))
    normalized = [normalize_scope_key(value) for value in values if normalize_scope_key(value)]
    return any(value in allowed for value in normalized)


def _apply_meeting_scope(payload: dict, user: User, session: Session) -> dict:
    scope = resolve_data_scope(user, session)
    result = dict(payload or {})
    if scope.unrestricted:
        result["scope"] = "all"
        return result
    allowed = {normalize_scope_key(value) for value in scope.owner_keys if normalize_scope_key(value)}
    rows = [row for row in result.get("meetings", []) or [] if allowed and _meeting_matches(row, allowed)]
    result["meetings"] = rows
    result["summary"] = _meeting_summary(rows)
    result["counts"] = _meeting_counts(rows)
    result["scope"] = scope.mode
    result["scope_message"] = "仅展示当前账号权限范围内且参与人可核验的会议"
    return result


def _load_meetings(
    start: str,
    finish: str,
    phone: str,
    name: str,
    user: User,
    session: Session,
) -> dict:
    scope = resolve_data_scope(user, session)
    if not scope.unrestricted and not scope.owner_keys:
        return {"ok": True, "date": start, "date_end": finish, "meetings": [], "summary": _meeting_summary([]), "counts": _meeting_counts([]), "scope": scope.mode}
    # Restricted callers may not choose another person.  Prefer the explicitly
    # configured source name used by Vemory; the result is filtered again after
    # normalization to prevent provider-side filter failures from leaking rows.
    requested_name = name if scope.unrestricted else str(getattr(user, "sales_name", "") or "")
    requested_phone = phone if scope.unrestricted else ""
    payload = _safe_bridge(
        bridge.api_meeting_center_meetings,
        start,
        requested_phone,
        requested_name,
        finish,
        default={"ok": False, "error": "会议数据服务不可用", "meetings": []},
    )
    return _apply_meeting_scope(payload, user, session)


def _safe_bridge(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("meeting bridge 失败 {}: {}", fn.__name__, exc)
        if default is not None:
            return default
        raise HTTPException(status_code=503, detail="会议数据服务暂时不可用")


@router.get("/api/meeting-center/summary")
async def summary(
    date: str | None = None,
    end_date: str | None = None,
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    start = require_iso_date(date or bridge.today_text())
    finish = require_iso_date(end_date, field="end_date") if end_date else ""
    payload = _load_meetings(start, finish, "", "", user, session)
    summary_row = dict(payload.get("summary") or {})
    summary_row["scope"] = payload.get("scope")
    return summary_row


@router.get("/api/meeting-center/meetings")
async def meetings(
    date: str | None = None,
    end_date: str | None = None,
    phone: str = Query(""),
    name: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    start = require_iso_date(date or bridge.today_text())
    finish = require_iso_date(end_date, field="end_date") if end_date else ""
    return _load_meetings(start, finish, phone, name, user, session)


@router.get("/api/meeting-center/people")
async def people(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    payload = _safe_bridge(bridge.api_meeting_center_people, default={"people": []})
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return {**payload, "scope": "all"}
    allowed = {normalize_scope_key(value) for value in scope.owner_keys if normalize_scope_key(value)}
    rows = []
    for person in payload.get("people", []) or []:
        values = [person] if not isinstance(person, dict) else [person.get("name"), person.get("display_name"), person.get("login")]
        if any(normalize_scope_key(value) in allowed for value in values if normalize_scope_key(value)):
            rows.append(person)
    return {**payload, "people": rows, "scope": scope.mode}


class DispatchBody(BaseModel):
    date: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    assignments: list[Any] | None = None


@router.post("/api/meeting-center/dispatch")
async def dispatch(
    body: DispatchBody,
    user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
):
    from app.models.sync import sync_meetings

    date_text = require_iso_date(body.date or bridge.today_text())
    scope = resolve_data_scope(user, session)
    if not scope.unrestricted:
        scoped = _load_meetings(date_text, date_text, "", "", user, session)
        meeting_id = str(body.meeting_id or "")
        if not meeting_id or not any(str(row.get("id") or "") == meeting_id for row in scoped.get("meetings", [])):
            raise HTTPException(status_code=403, detail="该会议不在当前账号的数据权限范围内")
        allowed = {normalize_scope_key(value) for value in scope.owner_keys if normalize_scope_key(value)}
        for item in body.assignments or []:
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail="待办负责人格式无效")
            owner = normalize_scope_key(item.get("owner") or item.get("assignee") or item.get("owner_name"))
            if not owner or owner not in allowed:
                raise HTTPException(status_code=403, detail="待办负责人不在当前团队权限范围内")
    result = _safe_bridge(bridge.api_meeting_center_dispatch, body.model_dump(), date_text)
    try:
        sync_meetings(date_text)
    except Exception as exc:
        logger.warning("sync_meetings 失败: {}", exc)
    return result
