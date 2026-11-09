from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RSVP(Base):
    __tablename__ = "rsvps"
    __table_args__ = (
        CheckConstraint("guest_count BETWEEN 1 AND 20", name="ck_rsvps_guest_count"),
        CheckConstraint(
            "attendance IN ("
            "'Wedding Ceremony (13 December 2026)', "
            "'Reception & Dinner (14 December 2026)', "
            "'Both Events', 'Unable to Attend')",
            name="ck_rsvps_attendance",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    guest_name: Mapped[str] = mapped_column(String(100), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    guest_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    attendance: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    email_outbox: Mapped["EmailOutbox"] = relationship(
        back_populates="rsvp",
        uselist=False,
        cascade="all, delete-orphan",
    )
