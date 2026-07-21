import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    created_at: datetime


class HolidaySettingsUpdateRequest(BaseModel):
    enabled: bool
    provider: Literal["calendarific", "openholidays"]
    country: str = Field(min_length=2, max_length=2)
    region: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("city")
    @classmethod
    def normalize_city(cls, value: str) -> str:
        return value.strip()


class HolidaySettingsResponse(BaseModel):
    enabled: bool
    provider: str
    country: str
    region: str
    city: str
    calendar_id: uuid.UUID | None = None
    synced_events: int = 0
