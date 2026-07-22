import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from ember.models.personal import PersonalItemKind


class PersonalItemCreate(BaseModel):
    kind: PersonalItemKind
    title: str = Field(min_length=1, max_length=240)
    data: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class PersonalItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    data: dict | None = None


class PersonalItemResponse(BaseModel):
    id: uuid.UUID
    kind: PersonalItemKind
    title: str
    data: dict
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
