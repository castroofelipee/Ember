import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ember.models.calendar import DEFAULT_CALENDAR_COLOR

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class CalendarCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("color must be a hex string like #4f46e5")
        return value


class CalendarResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    color: str
    created_at: datetime

    model_config = {"from_attributes": True}


__all__ = ["CalendarCreateRequest", "CalendarResponse", "DEFAULT_CALENDAR_COLOR"]
