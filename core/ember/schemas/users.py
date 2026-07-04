from zoneinfo import available_timezones

from pydantic import BaseModel, field_validator, model_validator

# A curated set for now rather than every BCP 47 tag; extend as locales are added.
SUPPORTED_LOCALES = ("en-US", "pt-BR", "es-ES", "fr-FR", "de-DE")
SUPPORTED_TIME_FORMATS = ("12h", "24h")

_VALID_TIMEZONES = available_timezones()


class PreferencesUpdateRequest(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    week_starts_on: int | None = None
    work_day_start: int | None = None
    work_day_end: int | None = None
    time_format: str | None = None

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_LOCALES:
            raise ValueError(f"locale must be one of {SUPPORTED_LOCALES}")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_TIMEZONES:
            raise ValueError("timezone must be a valid IANA timezone name")
        return value

    @field_validator("week_starts_on")
    @classmethod
    def validate_week_starts_on(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 6:
            raise ValueError("week_starts_on must be between 0 (Sunday) and 6 (Saturday)")
        return value

    @field_validator("work_day_start")
    @classmethod
    def validate_work_day_start(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 23:
            raise ValueError("work_day_start must be between 0 and 23")
        return value

    @field_validator("work_day_end")
    @classmethod
    def validate_work_day_end(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 24:
            raise ValueError("work_day_end must be between 1 and 24")
        return value

    @field_validator("time_format")
    @classmethod
    def validate_time_format(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_TIME_FORMATS:
            raise ValueError(f"time_format must be one of {SUPPORTED_TIME_FORMATS}")
        return value

    @model_validator(mode="after")
    def validate_work_hours_order(self) -> "PreferencesUpdateRequest":
        # Only enforce when both bounds are supplied in the same request; a
        # partial update against stored values is checked by the DB constraint.
        if (
            self.work_day_start is not None
            and self.work_day_end is not None
            and self.work_day_start >= self.work_day_end
        ):
            raise ValueError("work_day_start must be before work_day_end")
        return self


class PreferencesResponse(BaseModel):
    locale: str
    timezone: str
    week_starts_on: int
    work_day_start: int
    work_day_end: int
    time_format: str

    model_config = {"from_attributes": True}
