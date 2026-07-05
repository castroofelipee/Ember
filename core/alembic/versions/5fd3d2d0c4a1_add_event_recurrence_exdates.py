"""add event recurrence exdates

Revision ID: 5fd3d2d0c4a1
Revises: 214f5b079348
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5fd3d2d0c4a1"
down_revision: Union[str, Sequence[str], None] = "214f5b079348"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "events",
        sa.Column(
            "recurrence_exdates",
            postgresql.ARRAY(sa.DateTime(timezone=True)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "recurrence_exdates")
