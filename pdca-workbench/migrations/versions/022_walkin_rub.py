"""Preserve RUB revenue without adding it to existing USD totals."""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("walkin_daily_reports"):
        return  # Fresh databases create this model after the migration chain.
    columns = {column["name"] for column in inspector.get_columns("walkin_daily_reports")}
    if "deal_amount_rub" not in columns:
        op.add_column("walkin_daily_reports", sa.Column("deal_amount_rub", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("walkin_daily_reports", "deal_amount_rub")
