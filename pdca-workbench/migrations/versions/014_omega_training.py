"""Omega team training tables with a frozen, idempotent schema.

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

metadata = sa.MetaData()
utc = sa.DateTime(timezone=True)

cases = sa.Table(
    "omega_cases", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("team_key", sa.String(64), nullable=False),
    sa.Column("owner_id", sa.Integer, nullable=False),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("dealer_id", sa.String(36), nullable=False),
    sa.Column("draft_json", sa.String, nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("current_version", sa.Integer, nullable=False),
    sa.Column("confirmed_revision", sa.Integer, nullable=False),
    sa.Column("created_at", utc, nullable=False),
    sa.Column("updated_at", utc, nullable=False),
)
sa.Index("ix_omega_cases_team_key", cases.c.team_key)

versions = sa.Table(
    "omega_case_versions", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("case_id", sa.String(36), sa.ForeignKey("omega_cases.id"), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("snapshot_json", sa.String, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("confirmed_by", sa.Integer, nullable=False),
    sa.Column("created_at", utc, nullable=False),
    sa.UniqueConstraint("case_id", "version"),
)
sa.Index("ix_omega_case_versions_case_id", versions.c.case_id)

sessions = sa.Table(
    "omega_sessions", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("case_id", sa.String(36), sa.ForeignKey("omega_cases.id"), nullable=False),
    sa.Column("case_version_id", sa.String(36), sa.ForeignKey("omega_case_versions.id"), nullable=False),
    sa.Column("team_key", sa.String(64), nullable=False),
    sa.Column("owner_id", sa.Integer, nullable=False),
    sa.Column("mode", sa.String(20), nullable=False),
    sa.Column("source_meeting_id", sa.String(120), nullable=False),
    sa.Column("source_import_hash", sa.String(64), nullable=True),
    sa.Column("source_access_keys_json", sa.String, nullable=False),
    sa.Column("goal_timing", sa.String(12), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("transcript_hash", sa.String(64), nullable=False),
    sa.Column("created_at", utc, nullable=False),
    sa.Column("ended_at", utc, nullable=True),
    sa.UniqueConstraint("source_import_hash"),
)
sa.Index("ix_omega_sessions_case_id", sessions.c.case_id)
sa.Index("ix_omega_sessions_team_key", sessions.c.team_key)

segments = sa.Table(
    "omega_segments", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("speaker", sa.String(20), nullable=False),
    sa.Column("text", sa.String, nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("source_speaker", sa.String(120), nullable=False),
    sa.Column("asr_original", sa.String, nullable=False),
    sa.Column("request_key", sa.String(120), nullable=False),
    sa.Column("created_at", utc, nullable=False),
    sa.UniqueConstraint("session_id", "seq"),
)
sa.Index("ix_omega_segments_session_id", segments.c.session_id)

jobs = sa.Table(
    "omega_jobs", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("request_key", sa.String(120), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("priority", sa.Integer, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("available_at", utc, nullable=False),
    sa.Column("lease_token", sa.String(36), nullable=False),
    sa.Column("lease_until", utc, nullable=True),
    sa.Column("input_hash", sa.String(64), nullable=False),
    sa.Column("session_revision", sa.Integer, nullable=False),
    sa.Column("payload_json", sa.String, nullable=False),
    sa.Column("result_id", sa.String(36), nullable=False),
    sa.Column("error", sa.String, nullable=False),
    sa.Column("created_at", utc, nullable=False),
    sa.Column("updated_at", utc, nullable=False),
    sa.UniqueConstraint("session_id", "kind", "request_key"),
)
sa.Index("ix_omega_jobs_session_id", jobs.c.session_id)
sa.Index("ix_omega_jobs_status", jobs.c.status)
turn_predicate = sa.text("kind = 'turn' AND status IN ('queued', 'running')")
report_predicate = sa.text("kind = 'report' AND status IN ('queued', 'running', 'succeeded')")
sa.Index("uq_omega_one_pending_turn", jobs.c.session_id, unique=True,
         postgresql_where=turn_predicate, sqlite_where=turn_predicate)
sa.Index("uq_omega_active_report_input", jobs.c.session_id, jobs.c.input_hash,
         unique=True, postgresql_where=report_predicate, sqlite_where=report_predicate)

reports = sa.Table(
    "omega_reports", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
    sa.Column("input_hash", sa.String(64), nullable=False),
    sa.Column("content_json", sa.String, nullable=False),
    sa.Column("model", sa.String(128), nullable=False),
    sa.Column("prompt_version", sa.String(40), nullable=False),
    sa.Column("rubric_version", sa.String(40), nullable=False),
    sa.Column("created_at", utc, nullable=False),
)
sa.Index("ix_omega_reports_session_id", reports.c.session_id)

reviews = sa.Table(
    "omega_reviews", metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("report_id", sa.String(36), sa.ForeignKey("omega_reports.id"), nullable=False),
    sa.Column("reviewer_id", sa.Integer, nullable=False),
    sa.Column("content_json", sa.String, nullable=False),
    sa.Column("created_at", utc, nullable=False),
)
sa.Index("ix_omega_reviews_report_id", reviews.c.report_id)

heartbeats = sa.Table(
    "omega_worker_heartbeats", metadata,
    sa.Column("worker_id", sa.String(36), primary_key=True),
    sa.Column("started_at", utc, nullable=False),
    sa.Column("last_seen", utc, nullable=False),
)
sa.Index("ix_omega_worker_heartbeats_last_seen", heartbeats.c.last_seen)


def upgrade():
    bind = op.get_bind()
    for table in (cases, versions, sessions, segments, jobs, reports, reviews, heartbeats):
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in (heartbeats, reviews, reports, jobs, segments, sessions, versions, cases):
        table.drop(bind, checkfirst=True)
