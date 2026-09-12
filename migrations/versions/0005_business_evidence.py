"""Evaluator-owned business evidence without modifying historical runs."""

from alembic import op
from commerce_eval.storage.business_evidence import BusinessEvidenceRow

revision = "0005_business_evidence"
down_revision = "0004_provider_configs"
branch_labels = None
depends_on = None


def upgrade():
    BusinessEvidenceRow.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("business_evidence_downgrade_requires_explicit_export")
