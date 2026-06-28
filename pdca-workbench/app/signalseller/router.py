# -*- coding: utf-8 -*-
"""SignalSeller 获客 API。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.deps import require_role
from app.auth.models import User
from app.signalseller import outreach, service

router = APIRouter(prefix="/api/signalseller", tags=["signalseller"])


class OutreachGenerateBody(BaseModel):
    customer: dict[str, Any] = Field(default_factory=dict)
    template_type: str = "fabe_email"
    product: str = ""
    use_hermes: bool = False


def _owner_filter(user: User, owner: str) -> str | None:
    return service.resolve_owner_filter(
        user.role,
        getattr(user, "sales_name", "") or "",
        user.display_name,
        user.username,
        owner,
    )


@router.get("/summary")
async def signalseller_summary(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """CommandCenter 获客 KPI。"""
    owner_f = _owner_filter(user, owner)
    customers = service.load_customers(team, owner_f)
    return {
        "team": team,
        "owner": owner_f or "全部",
        "role": user.role,
        **service.build_summary(customers),
    }


@router.get("/customers")
async def signalseller_customers(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    abcd: str = Query("all"),
    overdue_only: bool = Query(False),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """带 ABCD 评分的客户列表。"""
    owner_f = _owner_filter(user, owner)
    rows = service.load_customers(team, owner_f, abcd, overdue_only)
    return {"count": len(rows), "items": rows, "owner": owner_f or "全部"}


@router.get("/followup-tasks")
async def signalseller_followup_tasks(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """FollowUpOrchestrator 今日建议任务。"""
    owner_f = _owner_filter(user, owner)
    customers = service.load_customers(team, owner_f)
    return {"items": service.followup_tasks(customers), "owner": owner_f or "全部"}


@router.get("/owners")
async def signalseller_owners(
    user: Annotated[User, Depends(require_role("manager"))],
    team: str = Query("yang-jingjing"),
):
    return {"items": service.list_owners(team)}


@router.get("/methodology")
async def signalseller_methodology(
    _user: Annotated[User, Depends(require_role("viewer"))],
):
    from app.config import get_settings
    import json

    path = get_settings().config_dir / "signalseller_methodology.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


@router.post("/outreach/generate")
async def signalseller_outreach_generate(
    body: OutreachGenerateBody,
    user: Annotated[User, Depends(require_role("sales"))],
):
    """OutreachCrafter · 生成 FABE/私信/SPIN 触达内容。"""
    return outreach.generate_outreach(
        body.customer,
        body.template_type,
        body.product or outreach.PRODUCT_DEFAULT,
        body.use_hermes,
    )
