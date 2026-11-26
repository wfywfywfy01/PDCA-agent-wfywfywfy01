"""Add an optional, unique VPS identity binding to existing PDCA accounts."""

from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "vps_user_id" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("vps_user_id", sa.BigInteger(), nullable=True))
    if "ix_users_vps_user_id" not in {index["name"] for index in inspector.get_indexes("users")}:
        op.create_index("ix_users_vps_user_id", "users", ["vps_user_id"], unique=True)


def downgrade():
    # Keep identity bindings on code rollback. Older code ignores this nullable column.
    pass
