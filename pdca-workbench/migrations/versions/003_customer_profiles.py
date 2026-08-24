# -*- coding: utf-8 -*-
"""003：客户画像表正式化 + 激活率列补丁守卫化

Revision ID: 003
Revises: 002
Create Date: 2026-08-21

收敛原则（P5 整改）：新表一律进 alembic 迁移链；已由运行时 create_all/
裸 ALTER 建过的对象用幂等守卫，保证新旧库 upgrade head 均一次通过。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── customer_profiles（P3 获客事实源；生产可能已被 create_all 建过，守卫化）──
    if not sa.inspect(op.get_bind()).has_table("customer_profiles"):
        op.create_table(
            "customer_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("team", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("dealer_name", sa.String(length=256), nullable=False),
            sa.Column("dealer_nickname", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("region", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("country", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("owner", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("priority", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("abcd_grade", sa.String(length=4), nullable=False, server_default=""),
            sa.Column("value_score", sa.Integer(), nullable=True),
            sa.Column("intent_score", sa.Integer(), nullable=True),
            sa.Column("lead_source", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("followup_round", sa.String(length=16), nullable=False, server_default="1"),
            sa.Column("referral_from", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("last_followup_date", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("next_action", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_customer_profiles_team", "customer_profiles", ["team"])
        op.create_index("ix_customer_profiles_dealer_name", "customer_profiles", ["dealer_name"])
        op.create_index("ix_customer_profiles_owner", "customer_profiles", ["owner"])

    # ── dealer_sales.activation_rate（与运行时裸 ALTER 等价，守卫化）──
    if sa.inspect(op.get_bind()).has_table("dealer_sales"):
        existing = {
            col["name"]
            for col in sa.inspect(op.get_bind()).get_columns("dealer_sales")
        }
        if "activation_rate" not in existing:
            op.add_column(
                "dealer_sales",
                sa.Column("activation_rate", sa.Float(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    # 对称回滚：仅移除本迁移明确创建的对象（表已存在时不删）
    if sa.inspect(op.get_bind()).has_table("customer_profiles"):
        op.drop_table("customer_profiles")
