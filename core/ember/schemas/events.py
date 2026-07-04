import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class EventCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=300)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    color: str | None = None
    # External guests, by email — the "share with people outside" case. Empty
    # by default; deduplicated, order-insensitive.
    attendees: list[EmailStr] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    @field_validator("description", "location")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("color must be a hex string like #4f46e5")
        return value

    @field_validator("attendees")
    @classmethod
    def dedupe_attendees(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for email in value:
            key = email.lower()
            if key not in seen:
                seen.add(key)
                unique.append(email)
        return unique

    @model_validator(mode="after")
    def validate_time_range(self) -> "EventCreateRequest":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class EventResponse(BaseModel):
    id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    color: str | None
    attendees: list[str]

    model_config = {"from_attributes": True}

    @field_validator("attendees", mode="before")
    @classmethod
    def flatten_attendees(cls, value: object) -> object:
        # Map the EventAttendee rows down to their emails when validating from
        # the ORM object; pass through if already a list of strings.
        if isinstance(value, list):
            return [item.email if hasattr(item, "email") else item for item in value]
        return value
