# -*- coding: utf-8 -*-
"""Vemory 会议待办（事实源）：pdca_tasks 增加 Vemory 来源字段

Revision ID: 004
Revises: 003
Create Date: 2026-08-20

与 app/database.py 的 _migrate_schema() 保持等价（幂等）：
  external_todo_id  VARCHAR(64)   Vemory 待办 ID（vemory:{id}），同步去重主键
  meeting_name      VARCHAR(256)  会议名称
  meeting_date      VARCHAR(10)   会议日期（Asia/Shanghai）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _index_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {idx["name"] for idx in insp.get_indexes(table)}


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
    _add_column("pdca_tasks", "external_todo_id", sa.String(64), server_default="")
    _add_column("pdca_tasks", "meeting_name", sa.String(256), server_default="")
    _add_column("pdca_tasks", "meeting_date", sa.String(10), server_default="")
    index_name = "ix_pdca_tasks_external_todo_id"
    if "pdca_tasks" in sa.inspect(op.get_bind()).get_table_names() and index_name not in _index_names("pdca_tasks"):
        op.create_index(index_name, "pdca_tasks", ["external_todo_id"])


def downgrade() -> None:
    index_name = "ix_pdca_tasks_external_todo_id"
    if index_name in _index_names("pdca_tasks"):
        op.drop_index(index_name, table_name="pdca_tasks")
    _drop_column("pdca_tasks", "meeting_date")
    _drop_column("pdca_tasks", "meeting_name")
    _drop_column("pdca_tasks", "external_todo_id")
