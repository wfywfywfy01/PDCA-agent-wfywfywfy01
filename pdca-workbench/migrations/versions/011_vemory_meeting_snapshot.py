# -*- coding: utf-8 -*-
"""Make Vemory meeting snapshots idempotent and source-aware.

Revision ID: 011
Revises: 010
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("meeting_records"):
        return
    if "source" not in _columns("meeting_records"):
        op.add_column(
            "meeting_records",
            sa.Column("source", sa.String(32), nullable=False, server_default="legacy"),
        )

    # Historical rows predate the unique key. Keep the newest snapshot for an ID
    # so the unique index can be applied without losing a valid recent record.
    rows = bind.execute(
        sa.text(
            "SELECT id, external_id FROM meeting_records "
            "ORDER BY external_id, CASE WHEN synced_at IS NULL THEN 1 ELSE 0 END, "
            "synced_at DESC, id DESC"
        )
    ).mappings()
    seen: set[str] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        external_id = str(row["external_id"] or "")
        if external_id in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(external_id)
    for record_id in duplicate_ids:
        bind.execute(sa.text("DELETE FROM meeting_records WHERE id = :id"), {"id": record_id})

    if "uq_meeting_records_external_id" not in _index_names("meeting_records"):
        op.create_index(
            "uq_meeting_records_external_id",
            "meeting_records",
            ["external_id"],
            unique=True,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("meeting_records"):
        return
    if "uq_meeting_records_external_id" in _index_names("meeting_records"):
        op.drop_index("uq_meeting_records_external_id", table_name="meeting_records")
    if "source" in _columns("meeting_records"):
        op.drop_column("meeting_records", "source")
