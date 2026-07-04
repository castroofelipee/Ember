import uuid
from datetime import datetime

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
