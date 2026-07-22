import enum
import uuid
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonalItemKind(str, enum.Enum):
    READING = "reading"
    HABIT = "habit"
    VISION = "vision"


class PersonalItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personal_items"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[PersonalItemKind] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    __table_args__ = (Index("ix_personal_items_user_kind", "user_id", "kind"),)
