# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）：pdca_tasks 增加催办状态字段

Revision ID: 003
Revises: 002
Create Date: 2026-08-18

与 app/database.py 的 _migrate_schema() 保持等价（幂等）：
  last_reminded_at     TIMESTAMP       最近一次催办时间（可空）
  last_reminded_round  VARCHAR(32)     最近一次催办轮次 morning/afternoon/manual/auto-*
  remind_count         INTEGER         累计催办次数
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _add_column(table: str, name: str, coltype, **kwargs) -> None:
    # pdca_tasks 可能尚未建表（老库走运行时 create_all），跳过列补丁。
    if not sa.inspect(op.get_bind()).has_table(table):
        return
    if name in _column_names(table):
        return
    op.add_column(table, sa.Column(name, coltype, **kwargs))


def _drop_column(table: str, name: str) -> None:
    if name in _column_names(table):
        op.drop_column(table, name)


def upgrade() -> None:
    _add_column("pdca_tasks", "last_reminded_at", sa.DateTime(), nullable=True)
    _add_column("pdca_tasks", "last_reminded_round", sa.String(32), server_default="")
    _add_column("pdca_tasks", "remind_count", sa.Integer(), server_default="0")


def downgrade() -> None:
    _drop_column("pdca_tasks", "remind_count")
    _drop_column("pdca_tasks", "last_reminded_round")
    _drop_column("pdca_tasks", "last_reminded_at")
