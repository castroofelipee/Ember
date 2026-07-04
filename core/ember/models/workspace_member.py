import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class WorkspaceMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Join table: which users belong to which workspaces, and with what role."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, native_enum=False, length=16, validate_strings=True),
        nullable=False,
        default=WorkspaceRole.MEMBER,
        server_default=WorkspaceRole.MEMBER.value,
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        Index("ix_workspace_members_workspace_id", "workspace_id"),
        Index("ix_workspace_members_user_id", "user_id"),
    )
