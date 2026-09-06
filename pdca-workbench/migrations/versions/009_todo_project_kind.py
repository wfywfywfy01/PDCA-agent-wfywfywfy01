# -*- coding: utf-8 -*-
"""项目类型：todo_projects 增加 kind（keyword/meeting/manual）

Revision ID: 009
Revises: 008
Create Date: 2026-08-28

keyword=关键词业务项目；meeting=会议主题自动收敛项目（executors 随待办负责人
自动刷新、全部完成自动闭环）；manual=管理员手工创建项目。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("todo_projects"):
        return
    if "kind" not in _column_names("todo_projects"):
        op.add_column(
            "todo_projects",
            sa.Column("kind", sa.String(16), server_default="keyword"),
        )


def downgrade() -> None:
    if "kind" in _column_names("todo_projects"):
        op.drop_column("todo_projects", "kind")
