"""Add isolated full-library read permission for knowledge MCP accounts."""
from alembic import op
import sqlalchemy as sa


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("users"):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "knowledge_read_all" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "knowledge_read_all",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade():
    op.drop_column("users", "knowledge_read_all")
