"""Link real-call reports to assigned practice and repeated attempts.

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
    op.create_table(
        "omega_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("omega_cases.id"), nullable=False),
        sa.Column("case_version_id", sa.String(36), sa.ForeignKey("omega_case_versions.id"), nullable=False),
        sa.Column("team_key", sa.String(64), nullable=False),
        sa.Column("assignee_id", sa.Integer, nullable=False),
        sa.Column("assigned_by", sa.Integer, nullable=False),
        sa.Column("source_report_id", sa.String(36), sa.ForeignKey("omega_reports.id")),
        sa.Column("target_dimension", sa.String(32), nullable=False),
        sa.Column("pass_percent", sa.Integer, nullable=False),
        sa.Column("instructions", sa.String(1000), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("case_id", "team_key", "assignee_id"):
        op.create_index(f"ix_omega_assignments_{name}", "omega_assignments", [name])
    op.add_column("omega_sessions", sa.Column("assignment_id", sa.String(36),
                                                 sa.ForeignKey("omega_assignments.id")))
    op.create_index("ix_omega_sessions_assignment_id", "omega_sessions", ["assignment_id"])


def downgrade():
    op.drop_index("ix_omega_sessions_assignment_id", table_name="omega_sessions")
    op.drop_column("omega_sessions", "assignment_id")
    for name in ("assignee_id", "team_key", "case_id"):
        op.drop_index(f"ix_omega_assignments_{name}", table_name="omega_assignments")
    op.drop_table("omega_assignments")
