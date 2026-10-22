"""Editable monthly department sales and MTO rules."""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("duzhan_monthly_metrics"):
        return
    from app.models.duzhan_monthly_metric import DuzhanMonthlyMetric

    DuzhanMonthlyMetric.__table__.create(op.get_bind())


def downgrade():
    op.drop_table("duzhan_monthly_metrics")
