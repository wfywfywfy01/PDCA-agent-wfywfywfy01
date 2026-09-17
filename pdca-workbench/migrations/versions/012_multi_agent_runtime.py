# -*- coding: utf-8 -*-
"""多智能体督战运行时：运行/事件/外发审批/ASR 产物 + pdca_tasks 扩展。

Revision ID: 012
Revises: 011（011 为 main 的 vemory_meeting_snapshot；本迁移与规格中 011 编号对应，因分支合入碰撞顺延为 012）
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_key", sa.String(128), nullable=False, unique=True),
            sa.Column("thread_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("run_type", sa.String(32), nullable=False, server_default="user_task"),
            sa.Column("source_type", sa.String(32), nullable=False, server_default=""),
            sa.Column("source_ref", sa.String(256), nullable=False, server_default=""),
            sa.Column("requested_by", sa.String(128), nullable=False, server_default=""),
            sa.Column("input_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("input_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("current_node", sa.String(64), nullable=False, server_default=""),
            sa.Column("result_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("result_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
            sa.Column("error_detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"])
        op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
        op.create_index("ix_agent_runs_run_type", "agent_runs", ["run_type"])
    if not sa.inspect(bind).has_table("agent_events"):
        op.create_table(
            "agent_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_key", sa.String(160), nullable=False, unique=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("producer", sa.String(64), nullable=False, server_default=""),
            sa.Column("group_channel_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])
        op.create_index("ix_agent_events_task_id", "agent_events", ["task_id"])
        op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
    if not sa.inspect(bind).has_table("agent_outbox"):
        op.create_table(
            "agent_outbox",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("channel_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("message_kind", sa.String(32), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("approval_policy", sa.String(32), nullable=False, server_default="manual_required"),
            sa.Column("approval_status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("approved_by", sa.String(128), nullable=False, server_default=""),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("send_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_outbox_channel_id", "agent_outbox", ["channel_id"])
        op.create_index("ix_agent_outbox_approval_status", "agent_outbox", ["approval_status"])
    if not sa.inspect(bind).has_table("meeting_asr_artifacts"):
        op.create_table(
            "meeting_asr_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("artifact_key", sa.String(160), nullable=False, unique=True),
            sa.Column("meeting_external_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("meeting_date", sa.String(10), nullable=False, server_default=""),
            sa.Column("provider", sa.String(32), nullable=False, server_default=""),
            sa.Column("provider_task_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("audio_source_ref", sa.String(512), nullable=False, server_default=""),
            sa.Column("audio_sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("language", sa.String(32), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("transcript_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("segments_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("confidence", sa.Numeric(), nullable=True),
            sa.Column("review_status", sa.String(32), nullable=False, server_default="unreviewed"),
            sa.Column("reviewed_by", sa.String(128), nullable=False, server_default=""),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
            sa.Column("error_detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_meeting_asr_artifacts_meeting_external_id",
            "meeting_asr_artifacts",
            ["meeting_external_id"],
        )
        op.create_index(
            "ix_meeting_asr_artifacts_meeting_date",
            "meeting_asr_artifacts",
            ["meeting_date"],
        )
    if sa.inspect(bind).has_table("pdca_tasks"):
        existing = _columns("pdca_tasks")
        for name, col in {
            "agent_run_id": sa.Column("agent_run_id", sa.Integer(), nullable=True),
            "group_channel_id": sa.Column("group_channel_id", sa.String(64), nullable=False, server_default=""),
            "source_ref": sa.Column("source_ref", sa.String(256), nullable=False, server_default=""),
            "due_at": sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            "closed_at": sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            "blocked_reason": sa.Column("blocked_reason", sa.String(512), nullable=False, server_default=""),
            "evidence_json": sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
            "verification_status": sa.Column(
                "verification_status", sa.String(32), nullable=False, server_default="unverified"
            ),
        }.items():
            if name not in existing:
                op.add_column("pdca_tasks", col)
        op.create_index("ix_pdca_tasks_agent_run_id", "pdca_tasks", ["agent_run_id"])
        op.create_index("ix_pdca_tasks_verification_status", "pdca_tasks", ["verification_status"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("pdca_tasks"):
        existing = _columns("pdca_tasks")
        for name in (
            "verification_status",
            "evidence_json",
            "blocked_reason",
            "closed_at",
            "due_at",
            "source_ref",
            "group_channel_id",
            "agent_run_id",
        ):
            if name in existing:
                op.drop_column("pdca_tasks", name)
    for table in (
        "meeting_asr_artifacts",
        "agent_outbox",
        "agent_events",
        "agent_runs",
    ):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)
