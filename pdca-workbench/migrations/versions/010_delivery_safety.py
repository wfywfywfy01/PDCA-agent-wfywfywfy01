# -*- coding: utf-8 -*-
"""群认领/打分字段与定时外发运行凭证。

Revision ID: 010
Revises: 009
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("pdca_tasks"):
        existing = _columns("pdca_tasks")
        if "claimed_at" not in existing:
            op.add_column("pdca_tasks", sa.Column("claimed_at", sa.DateTime(), nullable=True))
        if "score" not in existing:
            op.add_column("pdca_tasks", sa.Column("score", sa.Integer(), nullable=True))
        if "score_at" not in existing:
            op.add_column("pdca_tasks", sa.Column("score_at", sa.DateTime(), nullable=True))
    if not sa.inspect(op.get_bind()).has_table("scheduled_job_runs"):
        op.create_table(
            "scheduled_job_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_key", sa.String(128), nullable=False, unique=True),
            sa.Column("job_name", sa.String(64), nullable=False),
            sa.Column("bucket", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="sending"),
            sa.Column("detail", sa.String(512), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_scheduled_job_runs_run_key", "scheduled_job_runs", ["run_key"])
        op.create_index("ix_scheduled_job_runs_job_name", "scheduled_job_runs", ["job_name"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("scheduled_job_runs"):
        op.drop_table("scheduled_job_runs")
    if sa.inspect(op.get_bind()).has_table("pdca_tasks"):
        existing = _columns("pdca_tasks")
        for name in ("score_at", "score", "claimed_at"):
            if name in existing:
                op.drop_column("pdca_tasks", name)
