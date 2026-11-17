"""Read-only GTM contract. Source tasks and messages never become company counts."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field


Count = Annotated[int, Field(ge=0)]
Identifier = Annotated[int, Field(gt=0)]


class CompanyCounts(BaseModel):
    open: Count
    actionable: Count
    unstarted: Count
    overdue: Count
    replied_open: Count


class CompanyItem(BaseModel):
    owner_user_id: Identifier
    stage: str
    company_id: Identifier | None = None
    kind: str | None = None
    next_action: str | None = None
    next_due_at: AwareDatetime | None = None
    signals: list[str] = Field(default_factory=list)


class Owner(BaseModel):
    owner_user_id: Identifier
    owner_name: str | None = None


class CompanyOwner(Owner):
    open: Count | None = None
    actionable: Count | None = None
    unstarted: Count | None = None
    overdue: Count | None = None
    replied_open: Count | None = None


class MessageOrigin(BaseModel):
    group_id: str | None = None
    message_id: str | None = None
    dispatch_message_id: str | None = None
    occurred_at: AwareDatetime | None = None


class PendingReply(MessageOrigin):
    id: Identifier
    status: Literal["pending", "received"]
    reason_codes: list[str] = Field(max_length=30)


class OwnerPendingReply(PendingReply, Owner):
    pass


class LastProgress(BaseModel):
    id: Identifier
    at: AwareDatetime
    source: str | None
    stage: str
    origin: MessageOrigin | None = None


class SourceCounts(BaseModel):
    records: Count
    open: Count
    completed: Count
    actionable: Count
    overdue: Count
    unaccepted: Count
    no_progress: Count
    missing_due: Count
    missing_next_action: Count
    pending_reply: Count
    reply_processing: Count


class SourceOwner(SourceCounts, Owner):
    pass


class SourceTask(Owner):
    task_id: Identifier
    display_name: str | None
    route: str
    source_system: str
    report_id: str | None
    status: str
    stage: str
    accepted_at: AwareDatetime | None
    last_progress_at: AwareDatetime | None
    last_progress: LastProgress | None
    company_id: Identifier | None
    customer_stage: str | None
    customer_stage_status: Literal["unlinked", "unavailable", "unclassified", "recorded"]
    customer_stage_event_id: Identifier | None
    customer_stage_at: AwareDatetime | None
    next_due_at: AwareDatetime | None
    next_action: str | None = None
    overdue: bool | None
    unaccepted: bool
    no_progress: bool
    missing_due: bool
    missing_next_action: bool
    pending_reply: bool
    reply_processing: bool
    signals: list[str]
    pending_reply_count: Count
    processing_reply_count: Count
    pending_replies: list[PendingReply] = Field(max_length=20)
    pending_replies_truncated: bool
    stored_outreach_hold: bool
    outreach_hold_status: Literal["held", "not_checked"]


class Page(BaseModel):
    as_of: AwareDatetime
    total: Count
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=1_000_000)]
    has_more: bool


class SourcePage(Page):
    unit: Literal["source_task"]
    totals: SourceCounts
    by_owner: list[SourceOwner] = Field(max_length=100)
    items: list[SourceTask] = Field(max_length=100)


class PendingOwner(Owner):
    pending: Count
    received: Count


class ReplyPage(Page):
    unit: Literal["vps_message"]
    by_owner: list[PendingOwner] = Field(max_length=100)
    items: list[OwnerPendingReply] = Field(max_length=100)


class AcquisitionQueue(BaseModel):
    items: list[CompanyItem] = Field(max_length=100)
    by_owner: list[CompanyOwner] = Field(max_length=100)
    truncated: bool
    as_of: AwareDatetime | None = None
    totals: CompanyCounts | None = None
    source_tasks: SourcePage | None = None
    owner_pending_replies: ReplyPage | None = None


class AcquisitionQueueEnvelope(BaseModel):
    ok: Literal[True]
    data: AcquisitionQueue
