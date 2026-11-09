import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class Attendance(StrEnum):
    WEDDING_CEREMONY = "Wedding Ceremony (13 December 2026)"
    RECEPTION_DINNER = "Reception & Dinner (14 December 2026)"
    BOTH_EVENTS = "Both Events"
    UNABLE_TO_ATTEND = "Unable to Attend"


GuestName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
IdempotencyKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RSVPCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: GuestName
    mobile: str | None = Field(default=None, max_length=20)
    guests: int = Field(ge=1, le=20, strict=True)
    attendance: Attendance
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        digits = re.sub(r"\D", "", normalized)
        if (
            not re.fullmatch(r"\+?[0-9][0-9 ()-]*[0-9]", normalized)
            or not 7 <= len(digits) <= 15
        ):
            raise ValueError("Enter a valid phone number.")
        return normalized

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RSVPResponse(BaseModel):
    id: UUID
    status: str
    notification_status: str
