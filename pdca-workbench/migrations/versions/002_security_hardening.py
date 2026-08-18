# -*- coding: utf-8 -*-
"""安全加固：共享吊销/限速表 + 将运行时 schema 补丁正式化为迁移

Revision ID: 002
Revises: 001
Create Date: 2026-08-18

与 app/database.py 的 _migrate_schema() 保持等价（幂等）：
已有库升级后两者结果一致，旧库兜底逻辑可保留；新库直接走本迁移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _add_column(table: str, name: str, coltype, **kwargs) -> None:
    # 001 只建了 5 张初始表；其余表由运行时 create_all 补建。
    # 表不存在时跳过列补丁，避免新库迁移链失败。
    if not sa.inspect(op.get_bind()).has_table(table):
        return
    if name in _column_names(table):
        return
    op.add_column(table, sa.Column(name, coltype, **kwargs))


def _drop_column(table: str, name: str) -> None:
    if name in _column_names(table):
        op.drop_column(table, name)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # ── 共享安全状态表 ────────────────────────────────────────────────────
    op.create_table(
        "token_revocations",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "login_fail_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(256), nullable=False, index=True),
        sa.Column("failed_at", sa.Float(), nullable=False),
    )

    # ── 历史运行时补丁：users ─────────────────────────────────────────────
    _add_column("users", "sales_name", sa.String(128), server_default="")
    _add_column("users", "must_change_password", sa.Boolean(), server_default=sa.text("1" if dialect != "postgresql" else "TRUE"))
    _add_column("users", "pwd_version", sa.Integer(), server_default="0")
    _add_column("users", "dealer_id", sa.String(64), server_default="")
    _add_column("users", "owner_key", sa.String(128), server_default="")
    _add_column("users", "team_key", sa.String(64), server_default="")
    _add_column("users", "data_scope", sa.String(16), server_default="")

    # ── 历史运行时补丁：dealer_stores ─────────────────────────────────────
    _add_column("dealer_stores", "dealer_level", sa.String(8), server_default="L1")
    _add_column("dealer_stores", "sales_owner", sa.String(64), server_default="")
    _add_column("dealer_stores", "team_key", sa.String(64), server_default="overseas")

    # ── 历史运行时补丁：walkin_daily_reports ──────────────────────────────
    _add_column("walkin_daily_reports", "walkin_visits", sa.Integer(), server_default="0")
    _add_column("walkin_daily_reports", "cross_visits", sa.Integer(), server_default="0")
    _add_column("walkin_daily_reports", "recruit_visits", sa.Integer(), server_default="0")
    _add_column("walkin_daily_reports", "existing_visits", sa.Integer(), server_default="0")
    # 旧进店来源五列已废弃（自然进/预约/潜客/介绍/SA），运行时补丁会删除，
    # 这里保持一致，避免新 taxonomy 的 INSERT 因缺列 NOT NULL 约束失败。
    for legacy in ("prospect_visits", "appointment_visits", "referral_visits", "sa_visits"):
        _drop_column("walkin_daily_reports", legacy)

    # ── 历史运行时补丁：dealer_sales ──────────────────────────────────────
    _add_column("dealer_sales", "phone_qty", sa.Integer(), server_default="0")
    _add_column("dealer_sales", "activation_rate", sa.Float(), server_default="0")


def downgrade() -> None:
    op.drop_table("login_fail_records")
    op.drop_table("token_revocations")
