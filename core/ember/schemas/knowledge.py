import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ember.models.knowledge import EntityType, RelationSource


class EntityCreateRequest(BaseModel):
    type: EntityType = EntityType.TASK
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=100_000)
    properties: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class EntityUpdateRequest(BaseModel):
    type: EntityType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = Field(default=None, max_length=100_000)
    properties: dict | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class EntityResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    type: EntityType
    title: str
    content: str
    properties: dict
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeFolderCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    parent_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class KnowledgeFolderUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: uuid.UUID | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class KnowledgeFolderResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=100_000)
    folder_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class RelationCreateRequest(BaseModel):
    to_entity_id: uuid.UUID
    relation_type: str = Field(default="references", min_length=1, max_length=60)
    source: RelationSource = RelationSource.MANUAL
    metadata: dict = Field(default_factory=dict)


class RelationResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    relation_type: str
    source: RelationSource
    metadata: dict = Field(validation_alias="relation_metadata")
    created_at: datetime

    model_config = {"from_attributes": True}


class RelatedEntityResponse(BaseModel):
    entity: EntityResponse
    relation: RelationResponse
    direction: str


class BoardCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    initial_columns: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    @field_validator("initial_columns")
    @classmethod
    def normalize_initial_columns(cls, value: list[str]) -> list[str]:
        columns: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            key = stripped.lower()
            if stripped and key not in seen:
                columns.append(stripped)
                seen.add(key)
        return columns


class BoardColumnCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    status_key: str | None = Field(default=None, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class BoardColumnUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    status_key: str | None = Field(default=None, max_length=80)
    position: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class BoardColumnResponse(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    title: str
    position: int
    status_key: str | None

    model_config = {"from_attributes": True}


class BoardCardCreateRequest(BaseModel):
    entity_id: uuid.UUID
    column_id: uuid.UUID


class BoardCardCreateWithEntityRequest(BaseModel):
    column_id: uuid.UUID
    type: EntityType = EntityType.TASK
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=100_000)
    labels: list[str] = Field(default_factory=list, max_length=30)
    assignees: list[str] = Field(default_factory=list, max_length=30)
    due_date: str = Field(default="", max_length=40)
    recurrence: Literal["none", "daily"] = "none"
    checklist: list[dict] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    @field_validator("labels", "assignees")
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            key = stripped.lower()
            if stripped and key not in seen:
                items.append(stripped)
                seen.add(key)
        return items


class BoardCardMoveRequest(BaseModel):
    column_id: uuid.UUID
    position: int = Field(ge=0)


class BoardCardResponse(BaseModel):
    board_id: uuid.UUID
    entity: EntityResponse
    column_id: uuid.UUID
    position: int
    created_at: datetime
    updated_at: datetime


class BoardResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    columns: list[BoardColumnResponse] = Field(default_factory=list)
    cards: list[BoardCardResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
