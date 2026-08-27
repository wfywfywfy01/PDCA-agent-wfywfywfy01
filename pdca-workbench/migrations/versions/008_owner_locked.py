# -*- coding: utf-8 -*-
"""owner 锁定：手工修正的执行人不被 Vemory 同步重算覆盖

Revision ID: 008
Revises: 007
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("pdca_tasks"):
        return
    if "owner_locked" not in _column_names("pdca_tasks"):
        op.add_column("pdca_tasks", sa.Column("owner_locked", sa.Boolean(), server_default=sa.text("0")))


def downgrade() -> None:
    if "owner_locked" in _column_names("pdca_tasks"):
        op.drop_column("pdca_tasks", "owner_locked")
