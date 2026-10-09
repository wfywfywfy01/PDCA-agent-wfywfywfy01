"""Reusable presets and idempotent launch provenance.

Revision ID: 019
Revises: 018
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("omega_cases")}
    additions = (
        sa.Column("kind", sa.String(16), nullable=False, server_default="case"),
        sa.Column("source_template_version_id", sa.String(36)),
        sa.Column("launch_key", sa.String(120)),
        sa.Column("launch_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("initial_session_id", sa.String(36)),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("omega_cases", column)
    if "uq_omega_case_launch" not in {index["name"] for index in sa.inspect(bind).get_indexes("omega_cases")}:
        op.create_index("uq_omega_case_launch", "omega_cases", ["team_key", "owner_id", "launch_key"], unique=True)


def downgrade():
    op.drop_index("uq_omega_case_launch", table_name="omega_cases")
    for name in ("initial_session_id", "launch_hash", "launch_key", "source_template_version_id", "kind"):
        op.drop_column("omega_cases", name)
