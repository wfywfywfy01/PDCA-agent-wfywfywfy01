"""Durable growth delivery claims; preserve existing send history unchanged."""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    from app.growth.models import GrowthAsset, GrowthContent, GrowthDelivery, GrowthSend, GrowthUnsub

    for model in (GrowthAsset, GrowthContent, GrowthSend, GrowthUnsub, GrowthDelivery):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    # Removing claims would make an uncertain delivery eligible for another send.
    # Keep this safety/audit table and all historical sends on a code rollback.
    pass
