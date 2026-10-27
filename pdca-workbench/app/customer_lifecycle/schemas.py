from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Stage = Literal["pending", "lead", "contacted", "intent", "qualified", "ordered", "paid", "paused", "closed"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_dates(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("时间必须包含时区")
            return value.astimezone(timezone.utc)
        return value


class Facts(Input):
    entity_verified: bool | None = None
    decision_maker: str | None = Field(default=None, max_length=256)
    need: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None


class CustomerCreate(Input):
    name: str = Field(min_length=1, max_length=256)
    owner_user_id: int = Field(gt=0)
    route: int | None = Field(default=None, ge=1, le=7)
    assisted_routes: list[int] = Field(default_factory=list, max_length=7)
    source_note: str = Field(default="", max_length=2000)
    country: str = Field(default="", max_length=80)
    entity_verified: bool = False
    decision_maker: str = Field(default="", max_length=256)
    need: str = Field(default="", max_length=2000)
    next_action: str = Field(default="", max_length=2000)
    due_at: datetime | None = None


class CustomerPatch(Facts):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    owner_user_id: int | None = Field(default=None, gt=0)
    route: int | None = Field(default=None, ge=1, le=7)
    assisted_routes: list[int] | None = Field(default=None, max_length=7)
    source_note: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=80)


class IdentityCreate(Input):
    namespace: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.:-]*$")
    external_id: str = Field(min_length=1, max_length=256)


class ProposalCreate(Input):
    source_system: Literal["manual", "ai_sales", "duzhan_im", "duzhan"]
    event_id: str = Field(min_length=1, max_length=256)
    source_channel_id: str = Field(default="", max_length=256)
    source_message_id: str = Field(default="", max_length=256)
    external_namespace: str = Field(default="", max_length=100)
    external_id: str = Field(default="", max_length=256)
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=4000)
    proposed_stage: Stage
    changes: Facts = Field(default_factory=Facts)
    business_link_id: str | None = None

    @field_validator("source_system")
    @classmethod
    def source_alias(cls, value):
        return "duzhan_im" if value == "duzhan" else value

    @model_validator(mode="after")
    def source_identity(self):
        if bool(self.external_namespace) != bool(self.external_id):
            raise ValueError("外部命名空间与ID必须同时提供")
        if self.source_system != "manual" and not (self.external_namespace and self.external_id and self.source_message_id):
            raise ValueError("外部证据必须带已映射客户ID与原消息ID")
        if self.source_system == "duzhan_im" and not self.source_channel_id:
            raise ValueError("群证据必须带群ID")
        return self


class Review(Input):
    expected_version: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=120)
    reason: str = Field(default="", max_length=2000)


class BusinessLinkCreate(IdentityCreate):
    kind: Literal["order", "payment"]
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    document_ref: str = Field(min_length=5, max_length=1000)
    occurred_at: datetime
    order_link_id: str | None = None


class FinanceReview(Input):
    request_key: str = Field(min_length=8, max_length=120)
    note: str = Field(min_length=5, max_length=2000)
