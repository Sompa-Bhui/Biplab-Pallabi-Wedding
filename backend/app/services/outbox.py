import logging
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import EmailOutbox, RSVP
from app.services.email import send_rsvp_notification

logger = logging.getLogger(__name__)


def claim_next_job(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> tuple[UUID, UUID] | None:
    now = datetime.now(timezone.utc)
    claim_token = uuid4()
    with session_factory() as session, session.begin():
        job = session.scalar(
            select(EmailOutbox)
            .where(
                EmailOutbox.attempts < settings.outbox_max_attempts,
                or_(
                    (
                        (EmailOutbox.status == "pending")
                        & (EmailOutbox.next_attempt_at <= now)
                    ),
                    (
                        (EmailOutbox.status == "processing")
                        & (EmailOutbox.locked_until <= now)
                    ),
                ),
            )
            .order_by(EmailOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "processing"
        job.locked_until = now + timedelta(seconds=settings.outbox_lease_seconds)
        job.claim_token = claim_token
        return job.id, claim_token


def _owns_unexpired_lease(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    claim_token: UUID,
) -> bool:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        return (
            session.scalar(
                select(EmailOutbox.id).where(
                    EmailOutbox.id == job_id,
                    EmailOutbox.status == "processing",
                    EmailOutbox.claim_token == claim_token,
                    EmailOutbox.locked_until > now,
                )
            )
            is not None
        )


def _renew_lease(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    claim_token: UUID,
    settings: Settings,
) -> bool:
    now = datetime.now(timezone.utc)
    with session_factory() as session, session.begin():
        result = session.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.id == job_id,
                EmailOutbox.status == "processing",
                EmailOutbox.claim_token == claim_token,
                EmailOutbox.locked_until > now,
            )
            .values(locked_until=now + timedelta(seconds=settings.outbox_lease_seconds))
        )
        return result.rowcount == 1


def _renew_lease_until_stopped(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    claim_token: UUID,
    settings: Settings,
    stop: Event,
    lease_lost: Event,
) -> None:
    interval = _heartbeat_interval(settings)
    while not stop.wait(interval):
        try:
            if not _renew_lease(session_factory, job_id, claim_token, settings):
                lease_lost.set()
                logger.warning("Email outbox lease lost for job %s.", job_id)
                return
        except Exception:
            lease_lost.set()
            logger.error(
                "Could not renew email outbox lease for job %s (%s).",
                job_id,
                "database operation failed",
            )
            return


def _heartbeat_interval(settings: Settings) -> float:
    return max(0.1, settings.outbox_lease_seconds / 3)


def _finalize_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    claim_token: UUID,
    values: dict[str, object],
) -> bool:
    now = datetime.now(timezone.utc)
    with session_factory() as session, session.begin():
        result = session.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.id == job_id,
                EmailOutbox.status == "processing",
                EmailOutbox.claim_token == claim_token,
                EmailOutbox.locked_until > now,
            )
            .values(**values, claim_token=None, locked_until=None)
        )
        return result.rowcount == 1


def process_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    claim_token: UUID,
    settings: Settings,
    sender=send_rsvp_notification,
) -> None:
    with session_factory() as session:
        job = session.get(EmailOutbox, job_id)
        if job is None:
            logger.error("Claimed email outbox job disappeared: %s", job_id)
            return
        if (
            job.status != "processing"
            or job.claim_token != claim_token
            or job.locked_until is None
        ):
            logger.warning("Skipping stale email outbox claim for job %s.", job_id)
            return
        rsvp = session.get(RSVP, job.rsvp_id)
        if rsvp is None:
            _finalize_job(
                session_factory,
                job_id,
                claim_token,
                {
                    "status": "failed",
                    "last_error": "RSVP record is missing.",
                },
            )
            return
        session.expunge(rsvp)
        attempt = job.attempts + 1

    if not _owns_unexpired_lease(session_factory, job_id, claim_token):
        logger.warning("Skipping expired email outbox claim for job %s.", job_id)
        return

    stop_heartbeat = Event()
    lease_lost = Event()
    heartbeat = Thread(
        target=_renew_lease_until_stopped,
        args=(
            session_factory,
            job_id,
            claim_token,
            settings,
            stop_heartbeat,
            lease_lost,
        ),
        name=f"outbox-lease-{job_id}",
        daemon=True,
    )
    heartbeat.start()

    try:
        sender(rsvp, settings)
    except Exception as exc:
        stop_heartbeat.set()
        heartbeat.join()
        if lease_lost.is_set():
            return
        with session_factory() as session:
            job = session.get(EmailOutbox, job_id)
            if job is None or job.claim_token != claim_token:
                logger.warning("Skipping failure update for stale job claim %s.", job_id)
                return
        if attempt >= settings.outbox_max_attempts:
            values: dict[str, object] = {
                "status": "failed",
                "attempts": attempt,
                "last_error": type(exc).__name__,
            }
            logger.error("Email outbox job %s exhausted retries.", job_id)
        else:
            delay = min(60 * (2 ** (attempt - 1)), 6 * 60 * 60)
            values = {
                "status": "pending",
                "attempts": attempt,
                "last_error": type(exc).__name__,
                "next_attempt_at": datetime.now(timezone.utc) + timedelta(seconds=delay),
            }
            logger.warning(
                "Email outbox job %s failed (attempt %s); retry scheduled.",
                job_id,
                attempt,
            )
        if not _finalize_job(session_factory, job_id, claim_token, values):
            logger.warning("Skipping failure update for expired job claim %s.", job_id)
        return
    finally:
        stop_heartbeat.set()
        heartbeat.join()

    if lease_lost.is_set():
        logger.warning("Email outbox job %s completed after losing its lease.", job_id)
        return
    finalized = _finalize_job(
        session_factory,
        job_id,
        claim_token,
        {
            "status": "sent",
            "attempts": attempt,
            "sent_at": datetime.now(timezone.utc),
            "last_error": None,
        },
    )
    if not finalized:
        logger.warning("Skipping sent update for expired job claim %s.", job_id)


def run_once(
    session_factory: sessionmaker[Session],
    settings: Settings,
    sender=send_rsvp_notification,
) -> bool:
    claim = claim_next_job(session_factory, settings)
    if claim is None:
        return False
    job_id, claim_token = claim
    process_job(session_factory, job_id, claim_token, settings, sender=sender)
    return True
