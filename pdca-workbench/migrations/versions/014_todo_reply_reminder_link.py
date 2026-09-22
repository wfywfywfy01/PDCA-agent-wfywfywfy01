# -*- coding: utf-8 -*-
"""把人工回复稳定关联到原催办消息。

Revision ID: 014
Revises: 013
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("todo_replies")}
    if "remind_send_id" not in columns:
        op.add_column("todo_replies", sa.Column("remind_send_id", sa.Integer(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("todo_replies")}
    if "ix_todo_replies_remind_send_id" not in indexes:
        op.create_index(
            "ix_todo_replies_remind_send_id", "todo_replies", ["remind_send_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("todo_replies")}
    if "ix_todo_replies_remind_send_id" in indexes:
        op.drop_index("ix_todo_replies_remind_send_id", table_name="todo_replies")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("todo_replies")}
    if "remind_send_id" in columns:
        op.drop_column("todo_replies", "remind_send_id")
