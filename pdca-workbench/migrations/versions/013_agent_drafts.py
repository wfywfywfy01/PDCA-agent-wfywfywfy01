# -*- coding: utf-8 -*-
"""群 Agent 每档草稿表：影子草稿后台可审，正式草稿与 Outbox 对齐审计。

Revision ID: 013
Revises: 012
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('agent_drafts'):
        return
    op.create_table(
        'agent_drafts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('draft_key', sa.String(160), nullable=False, unique=True),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.Column('channel_id', sa.String(64), nullable=False, server_default=''),
        sa.Column('group_name', sa.String(128), nullable=False, server_default=''),
        sa.Column('group_type', sa.String(32), nullable=False, server_default=''),
        sa.Column('day', sa.String(10), nullable=False, server_default=''),
        sa.Column('slot', sa.String(8), nullable=False, server_default=''),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('approval_policy', sa.String(32), nullable=False, server_default='manual_required'),
        sa.Column('shadow', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_agent_drafts_draft_key', 'agent_drafts', ['draft_key'])
    op.create_index('ix_agent_drafts_channel_id', 'agent_drafts', ['channel_id'])
    op.create_index('ix_agent_drafts_day', 'agent_drafts', ['day'])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('agent_drafts'):
        op.drop_table('agent_drafts')
