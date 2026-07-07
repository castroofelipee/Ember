"""scope user_preferences to workspace

Revision ID: 554f441b34c6
Revises: 9b7c1d2e4f6a
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '554f441b34c6'
down_revision: Union[str, Sequence[str], None] = '9b7c1d2e4f6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_preferences', sa.Column('workspace_id', sa.Uuid(), nullable=True))

    # Backfill: attach each existing preferences row to the user's oldest
    # workspace membership, so today's single "global" settings become that
    # workspace's settings instead of vanishing.
    op.execute(
        """
        UPDATE user_preferences
        SET workspace_id = earliest.workspace_id
        FROM (
            SELECT DISTINCT ON (user_id) user_id, workspace_id
            FROM workspace_members
            ORDER BY user_id, created_at
        ) AS earliest
        WHERE user_preferences.user_id = earliest.user_id
        """
    )
    # A user with no workspace membership has nothing to attach preferences
    # to; that row is orphaned and gets recreated the next time they join or
    # create a workspace (see ember.services.users.get_preferences).
    op.execute("DELETE FROM user_preferences WHERE workspace_id IS NULL")

    op.alter_column('user_preferences', 'workspace_id', nullable=False)
    op.drop_constraint(op.f('uq_user_preferences_user_id'), 'user_preferences', type_='unique')
    op.create_foreign_key(
        op.f('fk_user_preferences_workspace_id_workspaces'),
        'user_preferences',
        'workspaces',
        ['workspace_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_unique_constraint(
        op.f('uq_user_preferences_user_id_workspace_id'),
        'user_preferences',
        ['user_id', 'workspace_id'],
    )
    op.create_index(
        op.f('ix_user_preferences_workspace_id'), 'user_preferences', ['workspace_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_preferences_workspace_id'), table_name='user_preferences')
    op.drop_constraint(
        op.f('uq_user_preferences_user_id_workspace_id'), 'user_preferences', type_='unique'
    )
    op.drop_constraint(
        op.f('fk_user_preferences_workspace_id_workspaces'), 'user_preferences', type_='foreignkey'
    )
    # Best-effort: collapses back to one row per user by keeping only the
    # oldest preferences row, matching pre-migration semantics.
    op.execute(
        """
        DELETE FROM user_preferences up
        USING user_preferences newer
        WHERE up.user_id = newer.user_id AND up.created_at > newer.created_at
        """
    )
    op.drop_column('user_preferences', 'workspace_id')
    op.create_unique_constraint(op.f('uq_user_preferences_user_id'), 'user_preferences', ['user_id'])
