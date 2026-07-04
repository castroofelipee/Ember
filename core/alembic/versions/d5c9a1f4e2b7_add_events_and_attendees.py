"""add events and event_attendees

Revision ID: d5c9a1f4e2b7
Revises: c3b8e2f1a9d4
Create Date: 2026-07-03 21:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5c9a1f4e2b7'
down_revision: Union[str, Sequence[str], None] = 'c3b8e2f1a9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'events',
        sa.Column('calendar_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('all_day', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['calendar_id'], ['calendars.id'], name=op.f('fk_events_calendar_id_calendars'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_events')),
    )
    op.create_index('ix_events_calendar_id', 'events', ['calendar_id'], unique=False)
    op.create_index('ix_events_start_at', 'events', ['start_at'], unique=False)
    op.create_index('ix_events_end_at', 'events', ['end_at'], unique=False)

    op.create_table(
        'event_attendees',
        sa.Column('event_id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], name=op.f('fk_event_attendees_event_id_events'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_event_attendees')),
        sa.UniqueConstraint('event_id', 'email', name='uq_event_attendees_event_email'),
    )
    op.create_index('ix_event_attendees_event_id', 'event_attendees', ['event_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_event_attendees_event_id', table_name='event_attendees')
    op.drop_table('event_attendees')
    op.drop_index('ix_events_end_at', table_name='events')
    op.drop_index('ix_events_start_at', table_name='events')
    op.drop_index('ix_events_calendar_id', table_name='events')
    op.drop_table('events')
