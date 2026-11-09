from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EmailOutbox, RSVP
from app.schemas.rsvp import RSVPCreate


class IdempotencyConflict(Exception):
    pass


def _same_submission(existing: RSVP, payload: RSVPCreate) -> bool:
    return (
        existing.guest_name == payload.name
        and existing.mobile == payload.mobile
        and existing.guest_count == payload.guests
        and existing.attendance == payload.attendance.value
        and existing.message == payload.message
    )


def create_rsvp(
    session: Session,
    payload: RSVPCreate,
    idempotency_key: str | None,
) -> tuple[RSVP, bool]:
    try:
        with session.begin():
            if idempotency_key:
                existing = session.scalar(
                    select(RSVP).where(RSVP.idempotency_key == idempotency_key)
                )
                if existing:
                    if not _same_submission(existing, payload):
                        raise IdempotencyConflict
                    return existing, False

            record = RSVP(
                guest_name=payload.name,
                mobile=payload.mobile,
                guest_count=payload.guests,
                attendance=payload.attendance.value,
                message=payload.message,
                idempotency_key=idempotency_key,
            )
            record.email_outbox = EmailOutbox(status="pending")
            session.add(record)
            session.flush()
    except IntegrityError:
        if idempotency_key:
            existing = session.scalar(
                select(RSVP).where(RSVP.idempotency_key == idempotency_key)
            )
            if existing:
                if not _same_submission(existing, payload):
                    raise IdempotencyConflict
                return existing, False
        raise
    return record, True


def get_rsvp(session: Session, rsvp_id: UUID) -> RSVP | None:
    return session.get(RSVP, rsvp_id)
