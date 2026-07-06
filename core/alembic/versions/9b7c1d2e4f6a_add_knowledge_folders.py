"""add knowledge folders

Revision ID: 9b7c1d2e4f6a
Revises: 8d91d5e2f3a4
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b7c1d2e4f6a"
down_revision: Union[str, Sequence[str], None] = "8d91d5e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("knowledge_folders"):
        return

    op.create_table(
        "knowledge_folders",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["knowledge_folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_folders_workspace_id", "knowledge_folders", ["workspace_id"]
    )
    op.create_index("ix_knowledge_folders_parent_id", "knowledge_folders", ["parent_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("knowledge_folders"):
        return

    op.drop_index("ix_knowledge_folders_parent_id", table_name="knowledge_folders")
    op.drop_index("ix_knowledge_folders_workspace_id", table_name="knowledge_folders")
    op.drop_table("knowledge_folders")
