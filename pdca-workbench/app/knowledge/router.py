"""Authenticated same-origin API for human and AI knowledge queries."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.scope import resolve_data_scope
from app.config import get_settings
from app.database import get_session
from app.knowledge.client import request_content, request_json, scoped_dealers


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class QueryBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    dealer_id: UUID | None = None
    category: str | None = Field(default=None, max_length=40)
    top_k: int = Field(default=8, ge=1, le=20)


class ExportBody(BaseModel):
    asset_id: UUID
    reason: str = Field(min_length=10, max_length=500)
    confirmation: Literal["export-original"]


@router.get("/scope")
async def knowledge_scope(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    settings = get_settings()
    scope = resolve_data_scope(user, session)
    return {
        "enabled": settings.knowledge_hub_enabled,
        "scope": scope.mode,
        "dealers": scoped_dealers(user, session),
        "can_export_original": user.role == "admin" and scope.unrestricted,
    }


@router.post("/search")
async def search_knowledge(
    body: QueryBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    return await request_json(
        "POST", "/v1/search", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=body.model_dump(mode="json", exclude_none=True),
    )


@router.post("/answers")
async def answer_knowledge(
    body: QueryBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    payload = body.model_dump(mode="json", exclude_none=True)
    payload["top_k"] = min(body.top_k, 10)
    return await request_json(
        "POST", "/v1/answers", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""), body=payload,
    )


@router.get("/assets/{asset_id}/content", response_model=None)
async def preview_asset(
    asset_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    return await request_content(
        "GET", f"/v1/assets/{asset_id}/content", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
    )


@router.post("/exports", response_model=None)
async def export_original(
    body: ExportBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    if user.role != "admin" or not resolve_data_scope(user, session).unrestricted:
        raise HTTPException(status_code=403, detail="仅管理员可导出原件")
    return await request_content(
        "POST", "/v1/exports", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=body.model_dump(mode="json"),
    )
