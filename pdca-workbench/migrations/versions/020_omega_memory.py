"""Scoped profiles, pending evidence proposals and frozen context provenance.

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def _table(name, *columns):
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def _index(name, table, columns, **options):
    if name not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns, **options)


def _column(table, column):
    if column.name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def _opportunity_foreign_keys():
    return [item for item in sa.inspect(op.get_bind()).get_foreign_keys("omega_cases")
            if item["constrained_columns"] == ["opportunity_id"]
            and item["referred_table"] == "omega_opportunities"]


def _opportunity_column():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("omega_cases")}
    if "opportunity_id" not in columns:
        if bind.dialect.name == "sqlite":
            # SQLite natively adds a nullable reference; existing rows and dependent tables stay intact.
            op.execute("ALTER TABLE omega_cases ADD COLUMN opportunity_id VARCHAR(36) "
                       "CONSTRAINT fk_omega_cases_opportunity REFERENCES omega_opportunities(id)")
        else:
            op.add_column("omega_cases", sa.Column("opportunity_id", sa.String(36), nullable=True))
    if not _opportunity_foreign_keys():
        if bind.dialect.name == "sqlite":
            # Repair a partially applied older migration without omitting its foreign key.
            with op.batch_alter_table("omega_cases") as batch:
                batch.create_foreign_key("fk_omega_cases_opportunity", "omega_opportunities", ["opportunity_id"], ["id"])
        else:
            op.create_foreign_key("fk_omega_cases_opportunity", "omega_cases", "omega_opportunities", ["opportunity_id"], ["id"])


def upgrade():
    _table("omega_opportunities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team_key", sa.String(64), nullable=False),
        sa.Column("dealer_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("team_key", "dealer_id"):
        _index("ix_omega_opportunities_" + column, "omega_opportunities", [column])
    _opportunity_column()
    _index("ix_omega_cases_opportunity_id", "omega_cases", ["opportunity_id"])
    _column("omega_sessions", sa.Column("context_snapshot_json", sa.String(), nullable=False, server_default=""))
    _column("omega_sessions", sa.Column("context_source_session_ids_json", sa.String(), nullable=False, server_default="[]"))
    _table("omega_memory_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("team_key", "kind", "subject_id"),
        sa.CheckConstraint("kind IN ('sales','dealer','opportunity')"))
    _index("ix_omega_memory_profiles_team_key", "omega_memory_profiles", ["team_key"])
    _table("omega_memory_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("omega_reports.id"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("reviewed_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("operation_requests_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("apply_request_key", sa.String(120), nullable=False, server_default=""),
        sa.Column("apply_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id"),
        sa.CheckConstraint("status IN ('pending','applied','dismissed')"))
    _index("ix_omega_memory_proposals_session_id", "omega_memory_proposals", ["session_id"])
    _table("omega_memory_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("omega_memory_profiles.id"), nullable=False),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("omega_memory_proposals.id"), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("classification", sa.String(20), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False, server_default="coach_only"),
        sa.Column("source_session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
        sa.Column("source_report_id", sa.String(36), sa.ForeignKey("omega_reports.id"), nullable=False),
        sa.Column("quotes_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("omega_memory_entries.id"), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("proposal_id", "item_id"),
        sa.CheckConstraint("classification IN ('source_fact','inference','seller_note')"),
        sa.CheckConstraint("audience = 'coach_only'"))
    for column in ("profile_id", "source_session_id"):
        _index("ix_omega_memory_entries_" + column, "omega_memory_entries", [column])
    _index("uq_omega_memory_current_section", "omega_memory_entries", ["profile_id", "section"],
                    unique=True, postgresql_where=sa.text("is_current = true"), sqlite_where=sa.text("is_current = 1"))
    _index("uq_omega_active_memory_input", "omega_jobs", ["session_id", "input_hash"], unique=True,
                    postgresql_where=sa.text("kind = 'memory' AND status IN ('queued', 'running', 'succeeded')"),
                    sqlite_where=sa.text("kind = 'memory' AND status IN ('queued', 'running', 'succeeded')"))


def downgrade():
    op.drop_index("uq_omega_active_memory_input", table_name="omega_jobs")
    op.drop_table("omega_memory_entries")
    op.drop_table("omega_memory_proposals")
    op.drop_table("omega_memory_profiles")
    op.drop_column("omega_sessions", "context_source_session_ids_json")
    op.drop_column("omega_sessions", "context_snapshot_json")
    op.drop_index("ix_omega_cases_opportunity_id", table_name="omega_cases")
    foreign_keys = _opportunity_foreign_keys()
    if op.get_bind().dialect.name == "sqlite":
        convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
        with op.batch_alter_table("omega_cases", naming_convention=convention) as batch:
            for item in foreign_keys:
                batch.drop_constraint(item["name"] or "fk_omega_cases_opportunity_id_omega_opportunities", type_="foreignkey")
            batch.drop_column("opportunity_id")
    else:
        for item in foreign_keys:
            op.drop_constraint(item["name"], "omega_cases", type_="foreignkey")
        op.drop_column("omega_cases", "opportunity_id")
    op.drop_table("omega_opportunities")
