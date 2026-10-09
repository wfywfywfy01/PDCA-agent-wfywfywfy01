"""Private help is stored outside the public negotiation transcript."""
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.omega.models import new_id, utcnow


class OmegaCoachHint(SQLModel, table=True):
    __tablename__ = "omega_coach_hints"
    __table_args__ = (UniqueConstraint("session_id", "request_key"),)

    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    session_id: str = Field(foreign_key="omega_sessions.id", index=True, max_length=36)
    request_key: str = Field(max_length=120)
    context_revision: int
    status: str = Field(default="queued", max_length=16)
    text: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
