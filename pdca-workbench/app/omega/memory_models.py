"""Reviewed memory records. Source text remains behind its original permission checks."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.omega.models import new_id, utcnow


class OmegaOpportunity(SQLModel, table=True):
    __tablename__ = "omega_opportunities"
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    team_key: str = Field(index=True, max_length=64)
    dealer_id: str = Field(index=True, max_length=36)
    owner_id: int
    title: str = Field(max_length=200)
    status: str = Field(default="active", max_length=20)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class OmegaMemoryProfile(SQLModel, table=True):
    __tablename__ = "omega_memory_profiles"
    __table_args__ = (UniqueConstraint("team_key", "kind", "subject_id"),
                      CheckConstraint("kind IN ('sales','dealer','opportunity')"))
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    team_key: str = Field(index=True, max_length=64)
    kind: str = Field(max_length=20)
    subject_id: str = Field(max_length=36)
    revision: int = Field(default=0)


class OmegaMemoryProposal(SQLModel, table=True):
    __tablename__ = "omega_memory_proposals"
    __table_args__ = (UniqueConstraint("report_id"),
                      CheckConstraint("status IN ('pending','applied','dismissed')"))
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    session_id: str = Field(foreign_key="omega_sessions.id", index=True, max_length=36)
    # Corrections retain the original source report in payload_json, without replacing its proposal.
    report_id: str | None = Field(default=None, foreign_key="omega_reports.id", max_length=36)
    revision: int = Field(default=1)
    status: str = Field(default="pending", max_length=20)
    payload_json: str = Field(default="{}")
    reviewed_json: str = Field(default="{}")
    operation_requests_json: str = Field(default="{}")
    apply_request_key: str = Field(default="", max_length=120)
    apply_hash: str = Field(default="", max_length=64)
    applied_by: int | None = None
    applied_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class OmegaMemoryEntry(SQLModel, table=True):
    __tablename__ = "omega_memory_entries"
    __table_args__ = (
        UniqueConstraint("proposal_id", "item_id"),
        CheckConstraint("classification IN ('source_fact','inference','seller_note')"),
        CheckConstraint("audience = 'coach_only'"),
        Index("uq_omega_memory_current_section", "profile_id", "section", unique=True,
              postgresql_where=text("is_current = true"), sqlite_where=text("is_current = 1")),
    )
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    profile_id: str = Field(foreign_key="omega_memory_profiles.id", index=True, max_length=36)
    proposal_id: str = Field(foreign_key="omega_memory_proposals.id", max_length=36)
    item_id: str = Field(max_length=36)
    section: str = Field(max_length=64)
    value: str
    classification: str = Field(max_length=20)
    audience: str = Field(default="coach_only", max_length=20)
    source_session_id: str = Field(foreign_key="omega_sessions.id", index=True, max_length=36)
    source_report_id: str = Field(foreign_key="omega_reports.id", max_length=36)
    quotes_json: str = Field(default="[]")
    created_by: int
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    supersedes_id: str | None = Field(default=None, foreign_key="omega_memory_entries.id", max_length=36)
    is_current: bool = Field(default=True)
