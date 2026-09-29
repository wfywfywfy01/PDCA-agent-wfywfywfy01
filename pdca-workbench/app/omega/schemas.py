"""Validated requests for negotiation training."""
from __future__ import annotations

from datetime import date
from typing import Literal

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


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
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
        return self


class CaseUpdate(CaseCreate):
    revision: int = Field(ge=1)


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
