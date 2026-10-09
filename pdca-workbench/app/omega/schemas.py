"""Validated requests for negotiation training."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.omega.reports import WEIGHTS


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_type: Literal["payment_commitment", "new_order", "schedule", "other"]
    success_condition: str = Field(min_length=5, max_length=1000)
    ideal: str = Field(min_length=2, max_length=1000)
    minimum: str = Field(min_length=2, max_length=1000)
    hard_limits: list[str] = Field(min_length=1, max_length=20)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    due_date: date | None = None

    @model_validator(mode="after")
    def require_payment_terms(self):
        if self.outcome_type == "payment_commitment" and (
            self.amount_minor is None or self.currency is None or self.due_date is None
        ):
            raise ValueError("回款目标须填写金额、币种和日期")
        if self.amount_minor is not None and not self.currency:
            raise ValueError("金额须附币种")
        if any(not value.strip() for value in self.hard_limits):
            raise ValueError("底线不能为空")
        return self


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="", max_length=100)
    is_primary: bool = False
    concerns: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(default_factory=list, max_length=12)
    known_facts: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(default_factory=list, max_length=20)
    decision_authority: str = Field(default="unknown", max_length=500)
    voice_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_content(self):
        if self.id.casefold() == "sales":
            raise ValueError("sales 是销售方保留人物标识")
        if not self.name.strip() or any(not item.strip() for item in self.concerns + self.known_facts):
            raise ValueError("人物名称、关注点和已知事实不能为空")
        if not self.decision_authority.strip():
            self.decision_authority = "unknown"
        return self


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    kind: Literal["case", "template"] = "case"
    source_template_version_id: str | None = Field(default=None, min_length=1, max_length=36)
    usage: Literal["training", "rehearsal", "real_review"] = "rehearsal"
    meeting_type: Literal["introduction", "discovery", "proposal", "negotiation", "order"] = "negotiation"
    stage_summary: str = Field(default="", max_length=1000)
    simulation: bool = True
    participants: list[Participant] = Field(default_factory=list, max_length=3)
    public_brief: str = Field(min_length=5, max_length=4000)
    seller_private: str = Field(default="", max_length=4000)
    counterparty_brief: str = Field(min_length=5, max_length=4000)
    buyer_name: str = Field(default="", max_length=100)
    buyer_role: str = Field(default="", max_length=100)
    buyer_company: str = Field(default="", max_length=120)
    buyer_emotion: str = Field(default="", max_length=120)
    buyer_objections: list[str] = Field(default_factory=list, max_length=12)
    score_weights: dict[str, int] = Field(default_factory=lambda: dict(WEIGHTS))
    dealer_id: str = Field(default="", max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    goal: Goal

    @model_validator(mode="after")
    def validate_scorecard(self):
        if (set(self.score_weights) != set(WEIGHTS)
                or any(type(value) is not int or value < 1 or value > 100
                       for value in self.score_weights.values())
                or sum(self.score_weights.values()) != 100):
            raise ValueError("评分卡须包含九项正整数权重，合计 100")
        if any(not value.strip() for value in self.buyer_objections):
            raise ValueError("买方异议不能为空")
        if self.participants and (sum(person.is_primary for person in self.participants) != 1
                or len({person.id for person in self.participants}) != len(self.participants)):
            raise ValueError("人物标识须唯一且恰有一位主要谈判对象")
        # Simulation is a server-validated property; real review never creates simulated output.
        self.simulation = self.usage != "real_review"
        return self


class CaseUpdate(CaseCreate):
    revision: int = Field(ge=1)


class TemplateStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=120)
    template_id: str = Field(min_length=1, max_length=36)
    template_version: int = Field(ge=1)
    usage: Literal["training", "rehearsal", "real_review"] = "training"
    dealer_id: str = Field(default="", max_length=36)
    opportunity_id: str | None = Field(default=None, max_length=36)
    overrides: dict = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def scenario_fields_only(cls, value: dict) -> dict:
        allowed = set(CaseCreate.model_fields) - {
            "kind", "usage", "dealer_id", "opportunity_id", "simulation", "source_template_version_id",
        }
        if set(value) - allowed:
            raise ValueError("仅允许调整场景字段")
        return value


class DraftAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("谈判描述不能为空")
        return value


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=120)
    text: str = Field(min_length=1, max_length=4000)
    source: Literal["text", "voice"] = "text"
    asr_original: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_voice_source(self):
        if self.source == "voice" and not self.asr_original.strip():
            raise ValueError("语音发言须保留原始转写")
        if self.source == "text" and self.asr_original:
            raise ValueError("文字发言不能附语音转写")
        return self


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=120)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: str = Field(min_length=5, max_length=5000)
    next_practice: str = Field(default="", max_length=1000)
