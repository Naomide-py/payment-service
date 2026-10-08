"""add payments.webhook_delivered_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 00:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payments "
        "ADD COLUMN IF NOT EXISTS webhook_delivered_at "
        "TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS webhook_delivered_at")
