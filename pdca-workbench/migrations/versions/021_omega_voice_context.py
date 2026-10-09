"""Private coaching, server voice state, and durable utterance identity.

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("omega_sessions")}
    for name, kind, default in (
        ("voice_state", sa.String(20), "idle"), ("audio_epoch", sa.Integer(), "0"),
        ("voice_control_key", sa.String(120), ""), ("voice_control_action", sa.String(20), ""),
    ):
        if name not in columns:
            op.add_column("omega_sessions", sa.Column(name, kind, nullable=False, server_default=default))
    columns = {column["name"] for column in inspector.get_columns("omega_segments")}
    for name in ("speaker_id", "turn_id", "provider_event_id"):
        if name not in columns:
            op.add_column("omega_segments", sa.Column(name, sa.String(120), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("omega_segments")}
    constraints = {item["name"] for item in inspector.get_unique_constraints("omega_segments")}
    if "uq_omega_segment_provider_event" not in indexes | constraints:
        op.create_index("uq_omega_segment_provider_event", "omega_segments",
                        ["session_id", "provider_event_id"], unique=True)
    if not inspector.has_table("omega_coach_hints"):
        op.create_table("omega_coach_hints",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("session_id", sa.String(36), sa.ForeignKey("omega_sessions.id"), nullable=False),
            sa.Column("request_key", sa.String(120), nullable=False),
            sa.Column("context_revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("session_id", "request_key"))
        op.create_index("ix_omega_coach_hints_session_id", "omega_coach_hints", ["session_id"])


def downgrade():
    op.drop_index("ix_omega_coach_hints_session_id", table_name="omega_coach_hints")
    op.drop_table("omega_coach_hints")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = [item for item in inspector.get_unique_constraints("omega_segments")
                   if item["column_names"] == ["session_id", "provider_event_id"]]
    constraint_names = {item["name"] for item in constraints}
    indexes = {item["name"] for item in inspector.get_indexes("omega_segments")}
    if "uq_omega_segment_provider_event" in indexes - constraint_names:
        op.drop_index("uq_omega_segment_provider_event", table_name="omega_segments")
    if bind.dialect.name == "sqlite":
        convention = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
        with op.batch_alter_table("omega_segments", naming_convention=convention) as batch:
            for item in constraints:
                batch.drop_constraint(item["name"] or "uq_omega_segments_session_id_provider_event_id", type_="unique")
            for name in ("provider_event_id", "turn_id", "speaker_id"):
                batch.drop_column(name)
    else:
        for item in constraints:
            op.drop_constraint(item["name"], "omega_segments", type_="unique")
        for name in ("provider_event_id", "turn_id", "speaker_id"):
            op.drop_column("omega_segments", name)
    for name in ("voice_control_action", "voice_control_key", "audio_epoch", "voice_state"):
        op.drop_column("omega_sessions", name)
