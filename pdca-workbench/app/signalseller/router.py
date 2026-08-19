# -*- coding: utf-8 -*-
"""SignalSeller APIs with mandatory server-side data scope."""
from __future__ import annotations

from typing import Annotated, Any

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

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


class CustomerUpdateBody(BaseModel):
    dealer_name: str
    team: str = "yang-jingjing"
    next_action: str | None = None
    abcd_grade: str | None = None
    followup_round: str | None = None
    last_followup_date: str | None = None
    value_score: int | None = None
    intent_score: int | None = None


@router.put("/customers")
async def signalseller_update_customer(
    body: CustomerUpdateBody,
    user: Annotated[User, Depends(require_role("sales"))],
    session: Annotated[Session, Depends(get_session)],
):
    """P3：更新客户跟进状态（写 customer_profiles，DB 唯一事实源）。

    sales 仅能更新自己权限范围内的客户；CSV 保留为导入素材，后续导入
    不会覆盖 DB 中已更新的字段（导入器按整行 upsert，运营时以 DB 为准）。
    """
    from app.models.customer_profile import CustomerProfile

    allowed, _label = _scoped_customers(body.team, user, session)
    requested = body.dealer_name.strip().casefold()
    if not any(
        str(row.get("dealer_name") or "").strip().casefold() == requested
        for row in allowed
    ):
        raise HTTPException(status_code=403, detail="该客户不在当前账号的数据权限范围内")

    row = session.exec(
        select(CustomerProfile).where(
            CustomerProfile.team == body.team,
            CustomerProfile.dealer_name == body.dealer_name.strip(),
        )
    ).first()
    if row is None:
        row = CustomerProfile(team=body.team, dealer_name=body.dealer_name.strip())
        session.add(row)
    if body.next_action is not None:
        row.next_action = body.next_action.strip()
    if body.abcd_grade is not None:
        grade = body.abcd_grade.strip().upper()
        if grade in ("A", "B", "C", "D"):
            row.abcd_grade = grade
    if body.followup_round is not None:
        row.followup_round = body.followup_round.strip()
    if body.last_followup_date is not None:
        from app.validation import require_iso_date

        row.last_followup_date = require_iso_date(
            body.last_followup_date, field="last_followup_date"
        )
    if body.value_score is not None:
        row.value_score = body.value_score
    if body.intent_score is not None:
        row.intent_score = body.intent_score
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return {"ok": True, "dealer_name": row.dealer_name}
