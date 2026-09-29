"""Link real-call reports to assigned practice and repeated attempts.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("omega_assignments"):
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
    assignment_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("omega_assignments")}
    for name in ("case_id", "team_key", "assignee_id"):
        index_name = f"ix_omega_assignments_{name}"
        if index_name not in assignment_indexes:
            op.create_index(index_name, "omega_assignments", [name])
    if "assignment_id" not in {column["name"] for column in inspector.get_columns("omega_sessions")}:
        # SQLite cannot add a foreign key without rebuilding the existing table; production uses PostgreSQL.
        column = (sa.Column("assignment_id", sa.String(36)) if bind.dialect.name == "sqlite"
                  else sa.Column("assignment_id", sa.String(36),
                                 sa.ForeignKey("omega_assignments.id")))
        op.add_column("omega_sessions", column)
    if "ix_omega_sessions_assignment_id" not in {
        index["name"] for index in sa.inspect(bind).get_indexes("omega_sessions")
    }:
        op.create_index("ix_omega_sessions_assignment_id", "omega_sessions", ["assignment_id"])


def downgrade():
    op.drop_index("ix_omega_sessions_assignment_id", table_name="omega_sessions")
    op.drop_column("omega_sessions", "assignment_id")
    for name in ("assignee_id", "team_key", "case_id"):
        op.drop_index(f"ix_omega_assignments_{name}", table_name="omega_assignments")
    op.drop_table("omega_assignments")
