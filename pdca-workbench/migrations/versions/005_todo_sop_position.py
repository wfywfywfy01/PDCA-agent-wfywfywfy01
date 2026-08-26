# -*- coding: utf-8 -*-
"""岗位 SOP 收敛：pdca_tasks 增加 position / origin_owner

Revision ID: 005
Revises: 004
Create Date: 2026-08-25

与 app/database.py 的 _migrate_schema() 保持等价（幂等）：
  position     VARCHAR(64)   岗位名（unclassified=未识别）
  origin_owner VARCHAR(128)  收敛前的会议参与人（owner 为收敛后执行人）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
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


def _drop_column(table: str, name: str) -> None:
    if name in _column_names(table):
        op.drop_column(table, name)


def upgrade() -> None:
    _add_column("pdca_tasks", "position", sa.String(64), server_default="")
    _add_column("pdca_tasks", "origin_owner", sa.String(128), server_default="")


def downgrade() -> None:
    _drop_column("pdca_tasks", "origin_owner")
    _drop_column("pdca_tasks", "position")
