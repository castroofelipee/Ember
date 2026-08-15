"""remove board docs

Revision ID: d4a8f13c6e29
Revises: c7f2b46a19de
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a8f13c6e29"
down_revision: Union[str, Sequence[str], None] = "c7f2b46a19de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(sa.text("DELETE FROM entities WHERE type = 'document'"))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("knowledge_folders"):
        return

    op.drop_index("ix_knowledge_folders_parent_id", table_name="knowledge_folders")
    op.drop_index("ix_knowledge_folders_workspace_id", table_name="knowledge_folders")
    op.drop_table("knowledge_folders")


def downgrade() -> None:
    """Downgrade schema.

    Recreates the empty table structure only — deleted document entities and
    folder rows are gone for good, this cannot restore them.
    """
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
