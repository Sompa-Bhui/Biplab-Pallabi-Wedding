from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.rsvp import IdempotencyKey, RSVPCreate, RSVPResponse
from app.services.rsvp import IdempotencyConflict, create_rsvp

router = APIRouter(prefix="/api/rsvp", tags=["rsvp"])


@router.post("", response_model=RSVPResponse, status_code=status.HTTP_201_CREATED)
def submit_rsvp(
    payload: RSVPCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    idempotency_key: Annotated[IdempotencyKey | None, Header(alias="Idempotency-Key")] = None,
) -> RSVPResponse:
    limiter = request.app.state.rate_limiter
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions. Please try again later.",
            headers={"Retry-After": str(get_settings().rate_limit_window_seconds)},
        )
    try:
        record, created = create_rsvp(session, payload, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with different RSVP data.",
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RSVP service is temporarily unavailable.",
        ) from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return RSVPResponse(
        id=record.id,
        status="created" if created else "existing",
        notification_status=record.email_outbox.status,
    )
