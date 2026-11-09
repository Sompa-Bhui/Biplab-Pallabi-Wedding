"""Create RSVP and transactional email outbox tables.

Revision ID: 0001_create_rsvp_email_outbox
Revises:
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_create_rsvp_email_outbox"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rsvps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guest_name", sa.String(length=100), nullable=False),
        sa.Column("mobile", sa.String(length=20), nullable=True),
        sa.Column("guest_count", sa.SmallInteger(), nullable=False),
        sa.Column("attendance", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("guest_count BETWEEN 1 AND 20", name="ck_rsvps_guest_count"),
        sa.CheckConstraint(
            "attendance IN ("
            "'Wedding Ceremony (13 December 2026)', "
            "'Reception & Dinner (14 December 2026)', "
            "'Both Events', 'Unable to Attend')",
            name="ck_rsvps_attendance",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rsvp_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["rsvp_id"], ["rsvps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rsvp_id"),
    )
    op.create_index("ix_email_outbox_due", "email_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_due", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_table("rsvps")
