# -*- coding: utf-8 -*-
"""IM 回复采集：pdca_tasks/todo_projects 回复字段 + im_remind_sends + todo_replies

Revision ID: 007
Revises: 006
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _add_column(table: str, name: str, coltype, **kwargs) -> None:
    if not sa.inspect(op.get_bind()).has_table(table):
        return
    if name in _column_names(table):
        return
    op.add_column(table, sa.Column(name, coltype, **kwargs))


def upgrade() -> None:
    _add_column("pdca_tasks", "reply_text", sa.String(1024), server_default="")
    _add_column("pdca_tasks", "replied_at", sa.DateTime(), nullable=True)
    _add_column("todo_projects", "reply_text", sa.String(1024), server_default="")
    _add_column("todo_projects", "replied_at", sa.DateTime(), nullable=True)
    op.create_table(
        "im_remind_sends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person", sa.String(128), nullable=False, index=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("message_id", sa.String(128), server_default=""),
        sa.Column("item_task_ids", sa.Text(), server_default="[]"),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("round", sa.String(32), server_default=""),
    )
    op.create_table(
        "todo_replies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person", sa.String(128), nullable=False, index=True),
        sa.Column("text", sa.String(1024), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("signal", sa.String(32), server_default=""),
        sa.Column("status", sa.String(32), server_default="unreviewed"),
        sa.Column("target_task_id", sa.Integer(), nullable=True),
        sa.Column("target_project_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("todo_replies")
    op.drop_table("im_remind_sends")
    _drop = lambda t, n: None  # noqa: E731
    if "reply_text" in _column_names("todo_projects"):
        op.drop_column("todo_projects", "reply_text")
    if "replied_at" in _column_names("todo_projects"):
        op.drop_column("todo_projects", "replied_at")
    if "reply_text" in _column_names("pdca_tasks"):
        op.drop_column("pdca_tasks", "reply_text")
    if "replied_at" in _column_names("pdca_tasks"):
        op.drop_column("pdca_tasks", "replied_at")
