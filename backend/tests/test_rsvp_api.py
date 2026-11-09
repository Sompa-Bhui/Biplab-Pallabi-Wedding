from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models import EmailOutbox, RSVP


VALID_PAYLOAD = {
    "name": "  Asha Guest ",
    "mobile": "+1 (555) 123-4567",
    "guests": 2,
    "attendance": "Both Events",
    "message": "  Best wishes!  ",
}


def test_postgres_urls_are_normalized_to_psycopg_driver():
    assert (
        Settings(database_url="postgresql://guest:password@db.example/rsvp")
        .sqlalchemy_database_url
        .startswith("postgresql+psycopg://")
    )
    assert (
        Settings(database_url="postgres://guest:password@db.example/rsvp")
        .sqlalchemy_database_url
        .startswith("postgresql+psycopg://")
    )
    assert (
        Settings(database_url="postgresql+psycopg://guest:password@db.example/rsvp")
        .sqlalchemy_database_url
        .startswith("postgresql+psycopg://")
    )


def test_health_checks_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_creates_rsvp_and_outbox_atomically(client, session_factory: sessionmaker):
    response = client.post(
        "/api/rsvp",
        json=VALID_PAYLOAD,
        headers={"Idempotency-Key": "guest-123"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "created"
    assert response.json()["notification_status"] == "pending"
    with session_factory() as session:
        rsvp = session.scalar(select(RSVP))
        outbox = session.scalar(select(EmailOutbox))
        assert rsvp.guest_name == "Asha Guest"
        assert rsvp.mobile == "+1 (555) 123-4567"
        assert rsvp.message == "Best wishes!"
        assert outbox.rsvp_id == rsvp.id
        assert outbox.status == "pending"


def test_idempotent_retry_returns_existing_rsvp(client, session_factory: sessionmaker):
    headers = {"Idempotency-Key": "same-request"}
    first = client.post("/api/rsvp", json=VALID_PAYLOAD, headers=headers)
    second = client.post("/api/rsvp", json=VALID_PAYLOAD, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["status"] == "existing"
    assert second.json()["id"] == first.json()["id"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RSVP)) == 1
        assert session.scalar(select(func.count()).select_from(EmailOutbox)) == 1


def test_idempotency_key_cannot_be_reused_with_different_data(client):
    headers = {"Idempotency-Key": "same-key"}
    assert client.post("/api/rsvp", json=VALID_PAYLOAD, headers=headers).status_code == 201
    changed = {**VALID_PAYLOAD, "guests": 3}
    response = client.post("/api/rsvp", json=changed, headers=headers)
    assert response.status_code == 409


def test_same_mobile_can_submit_multiple_rsvps(client, session_factory: sessionmaker):
    first = client.post("/api/rsvp", json=VALID_PAYLOAD)
    second = client.post("/api/rsvp", json={**VALID_PAYLOAD, "name": "Another Guest"})
    assert first.status_code == 201
    assert second.status_code == 201
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RSVP)) == 2


def test_guest_count_and_attendance_are_validated(client):
    for guests in (0, 21, "2", 2.5):
        response = client.post("/api/rsvp", json={**VALID_PAYLOAD, "guests": guests})
        assert response.status_code == 422
    response = client.post(
        "/api/rsvp",
        json={**VALID_PAYLOAD, "attendance": "5+ Persons"},
    )
    assert response.status_code == 422


def test_all_finalized_attendance_options_are_accepted(client):
    options = (
        "Wedding Ceremony (13 December 2026)",
        "Reception & Dinner (14 December 2026)",
        "Both Events",
        "Unable to Attend",
    )
    for attendance in options:
        response = client.post(
            "/api/rsvp",
            json={**VALID_PAYLOAD, "attendance": attendance},
        )
        assert response.status_code == 201


def test_optional_mobile_and_message(client):
    response = client.post(
        "/api/rsvp",
        json={
            "name": "Guest",
            "guests": 1,
            "attendance": "Unable to Attend",
        },
    )
    assert response.status_code == 201


def test_invalid_mobile_digit_count_is_rejected(client):
    response = client.post("/api/rsvp", json={**VALID_PAYLOAD, "mobile": "12345"})
    assert response.status_code == 422


def test_extra_fields_and_invalid_mobile_are_rejected(client):
    assert client.post(
        "/api/rsvp",
        json={**VALID_PAYLOAD, "unexpected": "field"},
    ).status_code == 422
    assert client.post(
        "/api/rsvp",
        json={**VALID_PAYLOAD, "mobile": "not-a-number"},
    ).status_code == 422
