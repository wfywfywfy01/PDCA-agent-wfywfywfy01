# -*- coding: utf-8 -*-
"""PDCA 与 Agent 辅助 API。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_role
from app.auth.models import User

router = APIRouter(tags=["pdca"])


class ProcessSuggestionBody(BaseModel):
    id: str | None = None
    suggestion: str | None = None
    mode: str | None = None
    date: str | None = None


@router.post("/api/agent/process-suggestion")
async def process_suggestion(
    body: ProcessSuggestionBody,
    _user: Annotated[User, Depends(require_role("sales"))],
):
    return {"ok": True, "message": "建议已记录", "id": body.id}
