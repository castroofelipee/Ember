"""add personal space

Revision ID: 6a4c8e2f1b90
Revises: 84f1c6a2d9b0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "6a4c8e2f1b90"
down_revision = "84f1c6a2d9b0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_items",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_items_user_kind", "personal_items", ["user_id", "kind"])


def downgrade():
    op.drop_index("ix_personal_items_user_kind", table_name="personal_items")
    op.drop_table("personal_items")
