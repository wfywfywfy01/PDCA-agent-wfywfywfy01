"""Authenticated profile reads and explicit owner review endpoints."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.omega import memory
from app.omega.memory_models import OmegaMemoryProposal, OmegaOpportunity
from app.omega.models import OmegaJob
from app.omega.router import enabled

router = APIRouter(prefix="/api/omega", tags=["omega-memory"], dependencies=[Depends(enabled)])
Actor = Annotated[User, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_session)]


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dealer_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=2, max_length=200)

    @field_validator("title")
    @classmethod
    def title_nonblank(cls, value):
        if not value.strip():
            raise ValueError("事项名称不能为空")
        return value.strip()


class RequestKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=120)


class ReviewRevision(RequestKey):
    expected_revision: int = Field(ge=1)


class ApplyRequest(ReviewRevision):
    accept_ids: list[str] = Field(min_length=1, max_length=12)
    edited_values: dict[str, str] = Field(default_factory=dict)


class CorrectionRequest(RequestKey):
    entry_id: str = Field(min_length=36, max_length=36)
    explanation: str = Field(min_length=1, max_length=2000)


def opportunity_view(row):
    return {"id": row.id, "dealer_id": row.dealer_id, "title": row.title,
            "status": row.status, "owner_id": row.owner_id}


@router.get("/opportunities")
def list_opportunities(dealer_id: str, user: Actor, db: Database):
    user = memory.current_actor(db, user)
    memory.require_dealer(user, db, dealer_id)
    return [opportunity_view(row) for row in db.exec(select(OmegaOpportunity).where(
        OmegaOpportunity.team_key == user.team_key, OmegaOpportunity.dealer_id == dealer_id)
        .order_by(OmegaOpportunity.created_at, OmegaOpportunity.id)).all()]


@router.post("/opportunities", status_code=201)
def create_opportunity(body: OpportunityCreate, user: Actor, db: Database):
    user = memory.current_actor(db, user)
    dealer_id = memory.require_dealer(user, db, body.dealer_id)
    row = OmegaOpportunity(team_key=user.team_key, owner_id=user.id, dealer_id=dealer_id, title=body.title)
    db.add(row)
    db.commit()
    return opportunity_view(row)


@router.get("/profiles")
def get_profile(kind: Literal["sales", "dealer", "opportunity"], subject_id: str, user: Actor, db: Database):
    return memory.profile_view(db, user, kind, subject_id)


@router.get("/reports/{report_id}/memory-proposal")
def get_memory_proposal(report_id: str, user: Actor, db: Database):
    user = memory.current_actor(db, user)
    report, game = memory.report_source(db, user, report_id)
    proposal = db.exec(select(OmegaMemoryProposal).where(OmegaMemoryProposal.report_id == report.id)).first()
    job = db.exec(select(OmegaJob).where(OmegaJob.session_id == game.id, OmegaJob.kind == "memory",
        OmegaJob.input_hash == memory.memory_input_hash(report, game)).order_by(OmegaJob.created_at.desc(), OmegaJob.id.desc())).first()
    generation = {"status": job.status if job else "not_requested", "job_id": job.id if job else None,
                  "error": "评分已完成，档案建议生成失败" if job and job.status == "failed" else ""}
    return {"proposal": memory.proposal_view(db, user, proposal) if proposal else None, "generation": generation}


@router.post("/memory-proposals/{proposal_id}/apply")
def apply_memory(proposal_id: str, body: ApplyRequest, user: Actor, db: Database):
    return memory.apply_proposal(db, user, proposal_id, **body.model_dump())


@router.post("/memory-proposals/{proposal_id}/dismiss")
def dismiss_memory(proposal_id: str, body: ReviewRevision, user: Actor, db: Database):
    return memory.dismiss_proposal(db, user, proposal_id, **body.model_dump())


@router.post("/memory-proposals/{proposal_id}/refresh")
def refresh_memory(proposal_id: str, body: ReviewRevision, user: Actor, db: Database):
    return memory.refresh_proposal(db, user, proposal_id, **body.model_dump())


@router.post("/reports/{report_id}/memory-proposal/retry", status_code=202)
def retry_memory(report_id: str, body: RequestKey, user: Actor, db: Database):
    user = memory.current_actor(db, user)
    report, _ = memory.report_source(db, user, report_id)
    try:
        job = memory.enqueue_memory_job(db, user, report, body.request_key)
        db.commit()
    except IntegrityError:
        db.rollback()
        job = memory.enqueue_memory_job(db, user, report, body.request_key)
        db.commit()
    return {"id": job.id, "kind": job.kind, "status": job.status, "result_id": job.result_id}


@router.post("/profiles/{profile_id}/corrections", status_code=201)
def correct_memory(profile_id: str, body: CorrectionRequest, user: Actor, db: Database):
    try:
        return memory.correction_proposal(db, user, profile_id, **body.model_dump())
    except IntegrityError:
        db.rollback()
        return memory.correction_proposal(db, user, profile_id, **body.model_dump())
