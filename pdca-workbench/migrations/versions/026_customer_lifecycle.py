"""Reviewed customer lifecycle, identity links and financial evidence."""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    from app.customer_lifecycle.models import (
        LifecycleAudit, LifecycleBusinessLink, LifecycleCustomer, LifecycleEvidence,
        LifecycleIdentity, LifecycleProposal,
    )
    for model in (LifecycleCustomer, LifecycleIdentity, LifecycleEvidence,
                  LifecycleBusinessLink, LifecycleProposal, LifecycleAudit):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    # Keep identity mappings and reviewed evidence on a code rollback.
    pass
