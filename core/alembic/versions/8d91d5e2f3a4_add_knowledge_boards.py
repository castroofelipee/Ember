"""add knowledge entities and boards

Revision ID: 8d91d5e2f3a4
Revises: 5fd3d2d0c4a1
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8d91d5e2f3a4"
down_revision: Union[str, Sequence[str], None] = "5fd3d2d0c4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entities",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entities_workspace_id", "entities", ["workspace_id"])
    op.create_index("ix_entities_workspace_title", "entities", ["workspace_id", "title"])
    op.create_index("ix_entities_workspace_type", "entities", ["workspace_id", "type"])

    op.create_table(
        "boards",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_boards_workspace_id", "boards", ["workspace_id"])

    op.create_table(
        "relations",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("from_entity_id", sa.UUID(), nullable=False),
        sa.Column("to_entity_id", sa.UUID(), nullable=False),
        sa.Column("relation_type", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=40), server_default="manual", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_entity_id",
            "to_entity_id",
            "relation_type",
            "source",
            name="uq_relations_unique_edge",
        ),
    )
    op.create_index("ix_relations_from_entity_id", "relations", ["from_entity_id"])
    op.create_index("ix_relations_to_entity_id", "relations", ["to_entity_id"])
    op.create_index("ix_relations_workspace_id", "relations", ["workspace_id"])

    op.create_table(
        "board_columns",
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status_key", sa.String(length=80), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("board_id", "position", name="uq_board_columns_board_position"),
    )
    op.create_index("ix_board_columns_board_id", "board_columns", ["board_id"])

    op.create_table(
        "board_cards",
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("column_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["column_id"], ["board_columns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("board_id", "entity_id"),
    )
    op.create_index(
        "ix_board_cards_board_column_position",
        "board_cards",
        ["board_id", "column_id", "position"],
    )
    op.create_index("ix_board_cards_entity_id", "board_cards", ["entity_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_board_cards_entity_id", table_name="board_cards")
    op.drop_index("ix_board_cards_board_column_position", table_name="board_cards")
    op.drop_table("board_cards")
    op.drop_index("ix_board_columns_board_id", table_name="board_columns")
    op.drop_table("board_columns")
    op.drop_index("ix_relations_workspace_id", table_name="relations")
    op.drop_index("ix_relations_to_entity_id", table_name="relations")
    op.drop_index("ix_relations_from_entity_id", table_name="relations")
    op.drop_table("relations")
    op.drop_index("ix_boards_workspace_id", table_name="boards")
    op.drop_table("boards")
    op.drop_index("ix_entities_workspace_type", table_name="entities")
    op.drop_index("ix_entities_workspace_title", table_name="entities")
    op.drop_index("ix_entities_workspace_id", table_name="entities")
    op.drop_table("entities")
