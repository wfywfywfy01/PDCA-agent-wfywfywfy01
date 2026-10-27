"""Separate business facts from imported statements and AI suggestions."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LifecycleCustomer(SQLModel, table=True):
    __tablename__ = "lifecycle_customers"
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    name: str = Field(max_length=256)
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    team_key: str = Field(index=True, max_length=64)
    route: int | None = None
    assisted_routes_json: str = Field(default="[]")
    source_note: str = Field(default="", max_length=2000)
    country: str = Field(default="", max_length=80)
    entity_verified: bool = False
    stage: str = Field(default="pending", max_length=20)
    highest_stage: str = Field(default="pending", max_length=20)
    decision_maker: str = Field(default="", max_length=256)
    need: str = Field(default="", max_length=2000)
    next_action: str = Field(default="", max_length=2000)
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    version: int = 1
    last_stage_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class LifecycleIdentity(SQLModel, table=True):
    __tablename__ = "lifecycle_identities"
    __table_args__ = (UniqueConstraint("namespace", "external_id", name="uq_lifecycle_external_identity"),)
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    customer_id: str = Field(foreign_key="lifecycle_customers.id", index=True, max_length=36)
    namespace: str = Field(max_length=100)
    external_id: str = Field(max_length=256)
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class LifecycleEvidence(SQLModel, table=True):
    __tablename__ = "lifecycle_evidence"
    __table_args__ = (UniqueConstraint("source_system", "event_id", name="uq_lifecycle_source_event"),)
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    customer_id: str = Field(foreign_key="lifecycle_customers.id", index=True, max_length=36)
    source_system: str = Field(max_length=40)
    event_id: str = Field(max_length=256)
    source_channel_id: str = Field(default="", max_length=256)
    source_message_id: str = Field(default="", max_length=256)
    source_message_key: str | None = Field(default=None, unique=True, max_length=64)
    identity_id: str | None = Field(default=None, foreign_key="lifecycle_identities.id", max_length=36)
    summary: str = Field(max_length=4000)
    occurred_at: datetime = Field(sa_type=DateTime(timezone=True))
    ingested_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    submitted_by: int = Field(foreign_key="users.id")
    payload_hash: str = Field(max_length=64)


class LifecycleBusinessLink(SQLModel, table=True):
    __tablename__ = "lifecycle_business_links"
    __table_args__ = (UniqueConstraint("kind", "namespace", "external_id", name="uq_lifecycle_business_record"),)
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    customer_id: str = Field(foreign_key="lifecycle_customers.id", index=True, max_length=36)
    kind: str = Field(max_length=20)
    namespace: str = Field(max_length=100)
    external_id: str = Field(max_length=256)
    amount: Decimal = Field(sa_type=Numeric(20, 2))
    currency: str = Field(max_length=3)
    document_ref: str = Field(max_length=1000)
    occurred_at: datetime = Field(sa_type=DateTime(timezone=True))
    order_link_id: str | None = Field(default=None, foreign_key="lifecycle_business_links.id", max_length=36)
    status: str = Field(default="pending", max_length=20)
    submitted_by: int = Field(foreign_key="users.id")
    verified_by: int | None = Field(default=None, foreign_key="users.id")
    verified_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    verification_note: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class LifecycleProposal(SQLModel, table=True):
    __tablename__ = "lifecycle_proposals"
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    customer_id: str = Field(foreign_key="lifecycle_customers.id", index=True, max_length=36)
    evidence_id: str = Field(foreign_key="lifecycle_evidence.id", unique=True, max_length=36)
    proposed_stage: str = Field(max_length=20)
    changes_json: str = Field(default="{}")
    business_link_id: str | None = Field(default=None, foreign_key="lifecycle_business_links.id", max_length=36)
    status: str = Field(default="pending", max_length=20)
    reviewed_by: int | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    reason: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class LifecycleAudit(SQLModel, table=True):
    __tablename__ = "lifecycle_audit"
    __table_args__ = (UniqueConstraint("customer_id", "request_key", name="uq_lifecycle_operation"),)
    id: str = Field(default_factory=uid, primary_key=True, max_length=36)
    customer_id: str = Field(foreign_key="lifecycle_customers.id", index=True, max_length=36)
    actor_user_id: int = Field(foreign_key="users.id")
    action: str = Field(max_length=40)
    request_key: str = Field(max_length=120)
    payload_hash: str = Field(max_length=64)
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
