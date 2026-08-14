# -*- coding: utf-8 -*-
"""Public server-to-server exchange endpoint for acquisition SSO."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.acquisition.service import consume_login_ticket
from app.database import get_session

router = APIRouter(prefix="/api/auth/acquisition", tags=["acquisition-auth"])


class TicketExchangeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)


@router.post("/exchange")
async def exchange_ticket(
    body: TicketExchangeRequest,
    session: Annotated[Session, Depends(get_session)],
):
    return {"ok": True, "profile": consume_login_ticket(body.code, session)}
