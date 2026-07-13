# -*- coding: utf-8 -*-
"""会议中心 API 路由。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from app.auth.deps import require_role
from app.auth.models import User
from app.legacy import bridge
from app.validation import require_iso_date

router = APIRouter(tags=["meeting"])


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
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    start = require_iso_date(date or bridge.today_text())
    finish = require_iso_date(end_date, field="end_date") if end_date else None
    return _safe_bridge(bridge.api_meeting_center_summary, start, finish, default=[])


@router.get("/api/meeting-center/meetings")
async def meetings(
    date: str | None = None,
    end_date: str | None = None,
    phone: str = Query(""),
    name: str = Query(""),
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    start = require_iso_date(date or bridge.today_text())
    finish = require_iso_date(end_date, field="end_date") if end_date else ""
    return _safe_bridge(
        bridge.api_meeting_center_meetings,
        start,
        phone,
        name,
        finish,
        default={"meetings": [], "total": 0},
    )


@router.get("/api/meeting-center/people")
async def people(
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _safe_bridge(bridge.api_meeting_center_people, default={"people": []})


class DispatchBody(BaseModel):
    date: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    assignments: list[Any] | None = None


@router.post("/api/meeting-center/dispatch")
async def dispatch(
    body: DispatchBody,
    user: Annotated[User, Depends(require_role("manager"))],
):
    from app.models.sync import sync_meetings

    date_text = require_iso_date(body.date or bridge.today_text())
    result = _safe_bridge(bridge.api_meeting_center_dispatch, body.model_dump(), date_text)
    try:
        sync_meetings(date_text)
    except Exception as exc:
        logger.warning("sync_meetings 失败: {}", exc)
    return result
