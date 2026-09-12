"""Normalized import drafts, immutable assets and evaluation history.

Revision ID: 0002_onboarding
Revises: 0001_initial
"""

from alembic import op
from commerce_eval.storage.upgrades import upgrade_onboarding

revision = "0002_onboarding"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_onboarding(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("evaluation_history_downgrade_requires_explicit_export")
