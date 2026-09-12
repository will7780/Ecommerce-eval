"""Initial local platform schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-09-11
"""

from alembic import op

from commerce_eval.storage.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

