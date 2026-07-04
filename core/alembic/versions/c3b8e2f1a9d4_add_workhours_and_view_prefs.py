"""add work hours and view prefs to user_preferences

Revision ID: c3b8e2f1a9d4
Revises: 7e41391839a4
Create Date: 2026-07-03 21:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3b8e2f1a9d4'
down_revision: Union[str, Sequence[str], None] = '7e41391839a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_preferences',
        sa.Column('work_day_start', sa.SmallInteger(), server_default='9', nullable=False),
    )
    op.add_column(
        'user_preferences',
        sa.Column('work_day_end', sa.SmallInteger(), server_default='17', nullable=False),
    )
    op.add_column(
        'user_preferences',
        sa.Column('time_format', sa.String(length=3), server_default='12h', nullable=False),
    )
    op.create_check_constraint(
        'work_day_start_range',
        'user_preferences',
        'work_day_start >= 0 AND work_day_start <= 23',
    )
    op.create_check_constraint(
        'work_day_end_range',
        'user_preferences',
        'work_day_end >= 1 AND work_day_end <= 24',
    )
    op.create_check_constraint(
        'work_day_start_before_end',
        'user_preferences',
        'work_day_start < work_day_end',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('work_day_start_before_end', 'user_preferences', type_='check')
    op.drop_constraint('work_day_end_range', 'user_preferences', type_='check')
    op.drop_constraint('work_day_start_range', 'user_preferences', type_='check')
    op.drop_column('user_preferences', 'time_format')
    op.drop_column('user_preferences', 'work_day_end')
    op.drop_column('user_preferences', 'work_day_start')
