# -*- coding: utf-8 -*-
"""新人培训 API。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_role
from app.auth.models import User
from app.onboarding import service

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class CompleteBody(BaseModel):
    module_id: str
    day: int = 1
    score: int = 100


@router.get("/curriculum")
async def onboarding_curriculum(
    _user: Annotated[User, Depends(require_role("viewer"))],
):
    return service.load_curriculum()


@router.get("/progress")
async def onboarding_progress(
    user: Annotated[User, Depends(require_role("viewer"))],
):
    return service.build_progress(user.username, user.role)


@router.post("/complete")
async def onboarding_complete(
    body: CompleteBody,
    user: Annotated[User, Depends(require_role("sales"))],
):
    """培训模块打卡。"""
    return service.complete_module(user.username, body.module_id, body.day, body.score, user.role)
