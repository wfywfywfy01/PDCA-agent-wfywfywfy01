"""One active realtime voice lease per Omega session.

Revision ID: 016
Revises: 015
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "provider_dialog_id" not in {column["name"] for column in inspector.get_columns("omega_sessions")}:
        op.add_column("omega_sessions", sa.Column(
            "provider_dialog_id", sa.String(120), nullable=False, server_default="",
        ))
    if "uq_omega_one_realtime_stream" not in {index["name"] for index in inspector.get_indexes("omega_jobs")}:
        op.create_index("uq_omega_one_realtime_stream", "omega_jobs", ["session_id"],
                        unique=True, postgresql_where=sa.text("kind = 'realtime' AND status = 'running'"),
                        sqlite_where=sa.text("kind = 'realtime' AND status = 'running'"))


def downgrade():
    op.drop_index("uq_omega_one_realtime_stream", table_name="omega_jobs")
    op.drop_column("omega_sessions", "provider_dialog_id")
