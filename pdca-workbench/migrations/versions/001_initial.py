# -*- coding: utf-8 -*-
"""初始表结构

Revision ID: 001
Revises:
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "dealer_sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("check_date", sa.String(10), nullable=False),
        sa.Column("dealer_name", sa.String(256), nullable=False),
        sa.Column("region", sa.String(64)),
        sa.Column("country", sa.String(64)),
        sa.Column("sell_in_wan", sa.Float()),
        sa.Column("sell_out_wan", sa.Float()),
        sa.Column("units", sa.Integer()),
        sa.Column("source_file", sa.String(512)),
        sa.Column("synced_at", sa.DateTime()),
    )
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_date", sa.String(10), nullable=False),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256)),
        sa.Column("content", sa.Text()),
        sa.Column("file_path", sa.String(512)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "pdca_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_date", sa.String(10), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("owner", sa.String(128)),
        sa.Column("status", sa.String(32)),
        sa.Column("priority", sa.String(32)),
        sa.Column("source", sa.String(128)),
        sa.Column("vps_todo_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "meeting_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_date", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("meeting_type", sa.String(32)),
        sa.Column("bucket", sa.String(32)),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("brief", sa.Text()),
        sa.Column("todos_json", sa.Text()),
        sa.Column("participants_json", sa.Text()),
        sa.Column("synced_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("meeting_records")
    op.drop_table("pdca_tasks")
    op.drop_table("daily_reports")
    op.drop_table("dealer_sales")
    op.drop_table("users")
