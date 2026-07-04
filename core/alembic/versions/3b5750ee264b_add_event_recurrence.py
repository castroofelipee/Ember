"""add event recurrence

Revision ID: 3b5750ee264b
Revises: e1a7c0b93f52
Create Date: 2026-07-04 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3b5750ee264b'
down_revision: Union[str, Sequence[str], None] = 'e1a7c0b93f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('events', sa.Column('recurrence_freq', sa.String(length=10), nullable=True))
    op.add_column(
        'events',
        sa.Column('recurrence_interval', sa.Integer(), server_default='1', nullable=False),
    )
    op.add_column(
        'events',
        sa.Column(
            'recurrence_by_weekday', postgresql.ARRAY(sa.SmallInteger()), nullable=True
        ),
    )
    op.add_column('events', sa.Column('recurrence_count', sa.Integer(), nullable=True))
    op.add_column(
        'events',
        sa.Column('recurrence_until', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('events', 'recurrence_until')
    op.drop_column('events', 'recurrence_count')
    op.drop_column('events', 'recurrence_by_weekday')
    op.drop_column('events', 'recurrence_interval')
    op.drop_column('events', 'recurrence_freq')
