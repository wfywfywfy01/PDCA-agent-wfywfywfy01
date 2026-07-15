# -*- coding: utf-8 -*-
"""SignalSeller APIs with mandatory server-side data scope."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth.deps import require_role
from app.auth.models import User
from app.auth.scope import resolve_data_scope
from app.database import get_session
from app.signalseller import outreach, service

router = APIRouter(prefix="/api/signalseller", tags=["signalseller"])


class OutreachGenerateBody(BaseModel):
    customer: dict[str, Any] = Field(default_factory=dict)
    template_type: str = "fabe_email"
    product: str = ""
    use_hermes: bool = False


def _scoped_customers(
    team: str,
    user: User,
    session: Session,
    *,
    owner: str = "",
    abcd: str = "all",
    overdue_only: bool = False,
    ref_date: str | None = None,
) -> tuple[list[dict], str]:
    scope = resolve_data_scope(user, session)
    selected_team = team if scope.unrestricted else service.DEFAULT_TEAM
    try:
        rows = service.load_customers(selected_team, None, abcd, overdue_only, ref_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="无效团队标识") from exc
    if scope.unrestricted:
        if owner.strip():
            wanted = owner.strip().casefold()
            rows = [
                row for row in rows
                if str(row.get("owner") or "").strip().casefold() == wanted
            ]
        return rows, owner.strip() or "全部"
    rows = service.filter_customers_by_scope(
        rows,
        owner_keys=scope.owner_keys,
        dealer_names=scope.dealer_names if user.role == "dealer" else (),
    )
    return rows, "当前权限范围"


@router.get("/summary")
async def signalseller_summary(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    ref_date: str | None = Query(None),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    customers, owner_label = _scoped_customers(
        team, user, session, owner=owner, ref_date=ref_date,
    )
    return {
        "team": team,
        "owner": owner_label,
        "role": user.role,
        **service.build_summary(customers),
    }


@router.get("/customers")
async def signalseller_customers(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    abcd: str = Query("all"),
    overdue_only: bool = Query(False),
    ref_date: str | None = Query(None),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    rows, owner_label = _scoped_customers(
        team,
        user,
        session,
        owner=owner,
        abcd=abcd,
        overdue_only=overdue_only,
        ref_date=ref_date,
    )
    return {"count": len(rows), "items": rows, "owner": owner_label}


@router.get("/followup-tasks")
async def signalseller_followup_tasks(
    team: str = Query("yang-jingjing"),
    owner: str = Query(""),
    ref_date: str | None = Query(None),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    customers, owner_label = _scoped_customers(
        team, user, session, owner=owner, ref_date=ref_date,
    )
    return {"items": service.followup_tasks(customers), "owner": owner_label}


@router.get("/owners")
async def signalseller_owners(
    user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
    team: str = Query("yang-jingjing"),
):
    scope = resolve_data_scope(user, session)
    selected_team = team if scope.unrestricted else service.DEFAULT_TEAM
    if scope.unrestricted:
        try:
            return {"items": service.list_owners(selected_team)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="无效团队标识") from exc
    allowed = {str(value).strip().casefold() for value in scope.owner_keys}
    return {
        "items": [
            value for value in service.list_owners(selected_team)
            if value.strip().casefold() in allowed
        ]
    }


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
    session: Annotated[Session, Depends(get_session)],
):
    requested_name = str(
        body.customer.get("dealer_name") or body.customer.get("name") or ""
    ).strip().casefold()
    allowed, _label = _scoped_customers(service.DEFAULT_TEAM, user, session)
    customer = next(
        (
            row for row in allowed
            if str(row.get("dealer_name") or "").strip().casefold() == requested_name
        ),
        None,
    )
    if customer is None:
        raise HTTPException(status_code=403, detail="该客户不在当前账号的数据权限范围内")
    return outreach.generate_outreach(
        customer,
        body.template_type,
        body.product or outreach.PRODUCT_DEFAULT,
        body.use_hermes,
    )
