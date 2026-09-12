"""Immutable nonsecret model providers and sanitized explicit probe status.

Revision ID: 0004_provider_configs
Revises: 0002_onboarding
"""

from alembic import op

from commerce_eval.providers.models import initialize_provider_schema

revision = "0004_provider_configs"
down_revision = "0002_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    initialize_provider_schema(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("provider_history_downgrade_requires_explicit_export")
