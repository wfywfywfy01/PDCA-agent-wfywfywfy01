"""Authenticated customer management and reviewed event ingestion API."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from . import service as s
from .models import LifecycleCustomer, LifecycleIdentity
from .schemas import (BusinessLinkCreate, CustomerCreate, CustomerPatch, FinanceReview,
                      IdentityCreate, ProposalCreate, Review)

router = APIRouter(prefix="/api/customer-lifecycle", tags=["customer-lifecycle"])
Actor = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_session)]


def write(db, operation, *args):
    try:
        result = operation(db, *args)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "记录或请求已存在，请刷新核对") from exc


@router.get("/meta")
def metadata(user: Actor, db: DB):
    s.actor(db, user)
    return {"stages": [{"value": key, "label": label} for key, label in s.STAGES.items()],
            "live_collection": False, "finance_verification": "manual_manager_review",
            "integration_status": "awaiting_upstream_interfaces",
            "scope_note": "仅已授权客户；外部证据需显式身份映射，候选建议须确认"}


@router.get("/owners")
def owners(user: Actor, db: DB):
    user, scope = s.actor(db, user)
    items = []
    for person in db.exec(select(User).where(User.is_active == True)).all():
        try:
            s.owner(db, user, scope, person.id)
        except HTTPException:
            continue
        items.append({"id": person.id, "display_name": person.display_name or person.username, "team_key": person.team_key})
    return {"items": items}


@router.get("/customers")
def customers(user: Actor, db: DB, q: str = Query("", max_length=256),
              namespace: str = Query("", max_length=100), external_id: str = Query("", max_length=256)):
    user, scope = s.actor(db, user)
    if bool(namespace) != bool(external_id):
        raise HTTPException(422, "命名空间与外部ID须同时提供")
    stmt = select(LifecycleCustomer)
    if namespace:
        stmt = stmt.join(LifecycleIdentity).where(LifecycleIdentity.namespace == namespace, LifecycleIdentity.external_id == external_id)
    rows = db.exec(stmt.order_by(LifecycleCustomer.updated_at.desc())).all()
    return {"items": [s.customer_view(db, row) for row in rows if s.allowed(scope, user, row)
                      and (not q or q.casefold() in row.name.casefold())]}


@router.post("/customers", status_code=201)
def create_customer(body: CustomerCreate, user: Actor, db: DB):
    row = write(db, s.create_customer, user, body)
    db.refresh(row)
    return s.customer_view(db, row)


@router.get("/customers/{customer_id}")
def detail(customer_id: str, user: Actor, db: DB):
    return s.detail(db, user, customer_id)


@router.patch("/customers/{customer_id}")
def patch_customer(customer_id: str, body: CustomerPatch, user: Actor, db: DB):
    write(db, s.patch_customer, user, customer_id, body)
    return s.detail(db, user, customer_id)


@router.post("/customers/{customer_id}/identities", status_code=201)
def add_identity(customer_id: str, body: IdentityCreate, user: Actor, db: DB):
    row = write(db, s.add_identity, user, customer_id, body)
    db.refresh(row)
    return s.dump(row)


@router.post("/customers/{customer_id}/proposals", status_code=201)
def submit_proposal(customer_id: str, body: ProposalCreate, user: Actor, db: DB):
    row = write(db, s.submit_proposal, user, customer_id, body)
    db.refresh(row)
    return s.proposal_view(row)


@router.post("/customers/{customer_id}/proposals/{proposal_id}/confirm")
def confirm(customer_id: str, proposal_id: str, body: Review, user: Actor, db: DB):
    write(db, s.review_proposal, user, customer_id, proposal_id, body, True)
    return s.detail(db, user, customer_id)


@router.post("/customers/{customer_id}/proposals/{proposal_id}/reject")
def reject(customer_id: str, proposal_id: str, body: Review, user: Actor, db: DB):
    write(db, s.review_proposal, user, customer_id, proposal_id, body, False)
    return s.detail(db, user, customer_id)


@router.post("/customers/{customer_id}/business-links", status_code=201)
def submit_business_link(customer_id: str, body: BusinessLinkCreate, user: Actor, db: DB):
    row = write(db, s.submit_business_link, user, customer_id, body)
    db.refresh(row)
    return s.dump(row)


@router.post("/customers/{customer_id}/business-links/{link_id}/verify")
def verify_business_link(customer_id: str, link_id: str, body: FinanceReview, user: Actor, db: DB):
    write(db, s.verify_business_link, user, customer_id, link_id, body)
    return s.detail(db, user, customer_id)
