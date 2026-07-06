import enum
import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EntityType(str, enum.Enum):
    TASK = "task"
    BUG = "bug"
    IDEA = "idea"
    DECISION = "decision"
    RFC = "rfc"
    EVENT = "event"
    MEETING = "meeting"
    EMAIL = "email"
    CUSTOMER_REQUEST = "customer_request"
    PR = "pr"
    INCIDENT = "incident"
    NOTE = "note"
    DOCUMENT = "document"


class RelationSource(str, enum.Enum):
    MANUAL = "manual"
    WIKI_LINK = "wiki_link"
    SYSTEM = "system"


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[EntityType] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    properties: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_entities_workspace_id", "workspace_id"),
        Index("ix_entities_workspace_type", "workspace_id", "type"),
        Index("ix_entities_workspace_title", "workspace_id", "title"),
    )


class KnowledgeFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_folders"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_folders.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index("ix_knowledge_folders_workspace_id", "workspace_id"),
        Index("ix_knowledge_folders_parent_id", "parent_id"),
    )


class Relation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source: Mapped[RelationSource] = mapped_column(
        String(40),
        nullable=False,
        default=RelationSource.MANUAL,
        server_default=RelationSource.MANUAL.value,
    )
    relation_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint(
            "from_entity_id",
            "to_entity_id",
            "relation_type",
            "source",
            name="uq_relations_unique_edge",
        ),
        Index("ix_relations_workspace_id", "workspace_id"),
        Index("ix_relations_from_entity_id", "from_entity_id"),
        Index("ix_relations_to_entity_id", "to_entity_id"),
    )


class Board(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "boards"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_boards_workspace_id", "workspace_id"),)


class BoardColumn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "board_columns"

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        UniqueConstraint("board_id", "position", name="uq_board_columns_board_position"),
        Index("ix_board_columns_board_id", "board_id"),
    )


class BoardCard(TimestampMixin, Base):
    __tablename__ = "board_cards"

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("board_columns.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_board_cards_board_column_position", "board_id", "column_id", "position"),
        Index("ix_board_cards_entity_id", "entity_id"),
    )
