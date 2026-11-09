from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models import EmailOutbox, RSVP
from app.schemas.rsvp import RSVPCreate
from app.services import outbox as outbox_service
from app.services.outbox import _renew_lease, claim_next_job, process_job, run_once
from app.services.rsvp import create_rsvp


def make_settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        smtp_username="sender@example.com",
        smtp_password="app-password",
        mail_from="sender@example.com",
        **overrides,
    )


def add_rsvp(session_factory):
    with session_factory() as session:
        record, _ = create_rsvp(
            session,
            RSVPCreate(name="Asha", guests=2, attendance="Both Events"),
            None,
        )
        return record.id


def test_outbox_sends_and_marks_email_sent(session_factory):
    rsvp_id = add_rsvp(session_factory)
    sent = []

    def sender(rsvp, settings):
        sent.append((rsvp.guest_name, settings.rsvp_recipient))

    assert run_once(session_factory, make_settings(), sender=sender)
    assert sent[0][0] == "Asha"
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "sent"
        assert job.attempts == 1
        assert job.sent_at is not None
        assert job.last_error is None


def test_outbox_retries_then_marks_job_failed(session_factory):
    rsvp_id = add_rsvp(session_factory)
    settings = make_settings(outbox_max_attempts=2)

    def failing_sender(_rsvp, _settings):
        raise RuntimeError("sensitive SMTP response must not be persisted")

    assert run_once(session_factory, settings, sender=failing_sender)
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "pending"
        assert job.attempts == 1
        assert job.last_error == "RuntimeError"
        job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    assert run_once(session_factory, settings, sender=failing_sender)
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "failed"
        assert job.attempts == 2


def test_stale_claim_cannot_send_or_finalize(session_factory):
    rsvp_id = add_rsvp(session_factory)
    settings = make_settings()
    claim = claim_next_job(session_factory, settings)
    assert claim is not None
    job_id, stale_token = claim

    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        job.claim_token = uuid4()
        session.commit()

    sent = []
    process_job(
        session_factory,
        job_id,
        stale_token,
        settings,
        sender=lambda *_args: sent.append(True),
    )
    assert sent == []
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "processing"
        assert job.attempts == 0


def test_expired_worker_cannot_overwrite_new_claim_result(session_factory):
    rsvp_id = add_rsvp(session_factory)
    settings = make_settings()
    claim = claim_next_job(session_factory, settings)
    assert claim is not None
    job_id, stale_token = claim
    newer_token = uuid4()

    def sender(_rsvp, _settings):
        with session_factory() as session:
            job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
            job.claim_token = newer_token
            job.status = "processing"
            job.locked_until = datetime.now(timezone.utc) + timedelta(seconds=60)
            session.commit()

    process_job(session_factory, job_id, stale_token, settings, sender=sender)
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "processing"
        assert job.claim_token == newer_token
        assert job.sent_at is None


def test_lease_renewal_requires_current_unexpired_claim(session_factory):
    rsvp_id = add_rsvp(session_factory)
    settings = make_settings(outbox_lease_seconds=30)
    claim = claim_next_job(session_factory, settings)
    assert claim is not None
    job_id, claim_token = claim

    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        original_expiry = job.locked_until

    assert _renew_lease(session_factory, job_id, claim_token, settings)
    with session_factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.locked_until > original_expiry
        job.claim_token = uuid4()
        session.commit()

    assert not _renew_lease(session_factory, job_id, claim_token, settings)


def test_worker_renews_lease_during_long_send(tmp_path, monkeypatch):
    database_path = tmp_path / "outbox.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    rsvp_id = add_rsvp(factory)
    settings = make_settings(outbox_lease_seconds=10)
    started = Event()
    release = Event()
    monkeypatch.setattr(outbox_service, "_heartbeat_interval", lambda _settings: 0.01)

    def sender(_rsvp, _settings):
        started.set()
        assert release.wait(timeout=3)

    worker = Thread(target=run_once, args=(factory, settings), kwargs={"sender": sender})
    worker.start()
    try:
        assert started.wait(timeout=2)
        with factory() as session:
            job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
            original_expiry = job.locked_until

        deadline = monotonic() + 2
        renewed = False
        while monotonic() < deadline:
            with factory() as session:
                job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
                renewed = job.locked_until > original_expiry
            if renewed:
                break
            sleep(0.01)
        assert renewed
        assert claim_next_job(factory, settings) is None
    finally:
        release.set()
        worker.join(timeout=3)
        engine.dispose()

    assert not worker.is_alive()
    with factory() as session:
        job = session.scalar(select(EmailOutbox).where(EmailOutbox.rsvp_id == rsvp_id))
        assert job.status == "sent"


def test_email_content_and_recipient():
    from app.services.email import send_rsvp_notification

    class FakeSMTP:
        messages = []

        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            return None

        def starttls(self, context):
            return None

        def login(self, username, password):
            assert username == "sender@example.com"
            assert password == "app-password"

        def send_message(self, message):
            self.messages.append(message)

    import smtplib

    original_smtp = smtplib.SMTP
    smtplib.SMTP = FakeSMTP
    try:
        rsvp = RSVP(
            guest_name="Guest",
            mobile=None,
            guest_count=3,
            attendance="Reception & Dinner (14 December 2026)",
            message="Congratulations",
        )
        send_rsvp_notification(rsvp, make_settings())
    finally:
        smtplib.SMTP = original_smtp

    message = FakeSMTP.messages[0]
    assert message["To"] == "bhuisompa001@gmail.com"
    assert message["Subject"] == "New Wedding RSVP – Biplab & Pallabi"
    body = message.get_content()
    assert "Guest name: Guest" in body
    assert "Mobile: Not provided" in body
    assert "Number of guests: 3" in body
    assert "Reception & Dinner" in body
    assert "Congratulations" in body
