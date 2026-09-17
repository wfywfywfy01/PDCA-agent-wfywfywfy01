# -*- coding: utf-8 -*-
"""统一结构化契约：所有 LLM 输出先经 Pydantic 校验，禁止直接执行自然语言。

契约与《多智能体督战系统实施规格》第 6 节对齐；字段语义以规格为准。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── 主 Agent ──────────────────────────────────────────────────────────────

class SupervisorAction(BaseModel):
    """主 Agent 计划中的一个动作。"""

    action_type: str = Field(
        description="collect / draft_summary / query_tasks / group_followup / "
        "approval_request / ask_user / noop"
    )
    target: str = Field(default="all", description="all / group channel / 数据源名")
    deadline: Optional[str] = Field(default=None)
    reason: str = Field(default="")


class SupervisorDecision(BaseModel):
    """主 Agent 结构化决策（LLM 输出的唯一形状）。"""

    intent: str = Field(
        description="known_readonly_query / department_summary / group_followup / "
        "scheduled_event / risky_action / ask_user"
    )
    summary: str = Field(default="", max_length=2000)
    target_groups: list[str] = Field(default_factory=list)
    actions: list[SupervisorAction] = Field(default_factory=list)
    approval_required: bool = Field(default=False)
    unknowns: list[str] = Field(default_factory=list)

    @field_validator("target_groups", "unknowns")
    @classmethod
    def _cap_lists(cls, value: list[str]) -> list[str]:
        return value[:100]


# ── 群任务 / 证据 / 群结果 ────────────────────────────────────────────────

class GroupTask(BaseModel):
    """群级任务契约（对应 pdca_tasks 的 Agent 视图）。"""

    task_id: Optional[int] = Field(default=None)
    group_channel_id: str = Field(default="", max_length=64)
    owner: str = Field(default="", max_length=128)
    objective: str = Field(default="", max_length=512)
    expected_evidence: list[str] = Field(default_factory=list)
    deadline: Optional[str] = Field(default=None)
    risk_level: Literal["low", "medium", "high"] = Field(default="medium")
    source_refs: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """证据条目：每条结论必须能追溯来源。"""

    evidence_id: str = Field(default="", max_length=128)
    evidence_type: str = Field(
        default="manual_confirmation",
        description="im_message / whatsapp_metric / whatsapp_message / "
        "vemory_transcript / doubao_transcript / vps_activity / daily_report / "
        "mto_image / mto_quote / payment_receipt / manual_confirmation",
    )
    source: str = Field(default="")
    source_ref: str = Field(default="", max_length=256)
    subject: str = Field(default="", max_length=128)
    customer: str = Field(default="", max_length=128)
    captured_at: Optional[str] = Field(default=None)
    summary: str = Field(default="", max_length=1000)
    raw_available: bool = Field(default=False)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GroupAgentOutput(BaseModel):
    """群 Agent 结构化输出（第 6.4 节）。"""

    group_channel_id: str = Field(default="", max_length=64)
    slot: str = Field(default="", max_length=8)
    facts: list[dict] = Field(default_factory=list)
    progress_changes: list[dict] = Field(default_factory=list)
    blocked_tasks: list[GroupTask] = Field(default_factory=list)
    missing_evidence: list[GroupTask] = Field(default_factory=list)
    next_actions: list[dict] = Field(default_factory=list)
    draft_message: str = Field(default="", max_length=8000)
    approval_policy: Literal["auto_template", "manual_required", "manual_if_risky"] = (
        Field(default="auto_template")
    )
    unknowns: list[str] = Field(default_factory=list)


# ── 视觉 / ASR ────────────────────────────────────────────────────────────

class VisionResult(BaseModel):
    """MTO 图片结构化结果（第 6.5 节）。"""

    image_id: str = Field(default="", max_length=128)
    owner: str = Field(default="", max_length=128)
    source_ref: str = Field(default="", max_length=256)
    duplicate_of: Optional[str] = Field(default=None)
    ocr_text: str = Field(default="")
    product: str = Field(default="")
    material: str = Field(default="")
    color: str = Field(default="")
    quote_wan: Optional[float] = Field(default=None)
    qualifies: Optional[bool] = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    review_status: Literal["verified", "pending_manual", "rejected"] = Field(
        default="pending_manual"
    )


class AsrSegment(BaseModel):
    speaker: str = Field(default="")
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(default=0, ge=0)
    text: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AsrResult(BaseModel):
    """ASR 转写结果（第 6.6 节）。"""

    meeting_external_id: str = Field(default="", max_length=64)
    provider: str = Field(default="doubao")
    status: Literal["completed", "failed", "blocked"] = Field(default="completed")
    language: str = Field(default="zh-en", max_length=32)
    text: str = Field(default="")
    segments: list[AsrSegment] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    needs_manual_review: bool = Field(default=False)
