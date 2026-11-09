"""Add ownership tokens to email outbox leases.

Revision ID: 0002_email_outbox_claim_token
Revises: 0001_create_rsvp_email_outbox
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_email_outbox_claim_token"
down_revision: Union[str, None] = "0001_create_rsvp_email_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_outbox",
        sa.Column("claim_token", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_outbox", "claim_token")
