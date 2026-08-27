# -*- coding: utf-8 -*-
"""待办项目（事项）收敛：todo_projects 表 + pdca_tasks.project_id

Revision ID: 006
Revises: 005
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    op.create_table(
        "todo_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), server_default="新建"),
        sa.Column("executors", sa.String(512), server_default="[]"),
        sa.Column("coordinator", sa.String(128), server_default=""),
        sa.Column("last_reminded_at", sa.DateTime(), nullable=True),
        sa.Column("last_reminded_round", sa.String(32), server_default=""),
        sa.Column("remind_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    if "pdca_tasks" in sa.inspect(op.get_bind()).get_table_names():
        if "project_id" not in _column_names("pdca_tasks"):
            op.add_column("pdca_tasks", sa.Column("project_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "project_id" in _column_names("pdca_tasks"):
        op.drop_column("pdca_tasks", "project_id")
    op.drop_table("todo_projects")
