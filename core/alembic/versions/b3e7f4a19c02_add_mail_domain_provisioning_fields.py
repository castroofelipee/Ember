"""add mail domain provisioning fields

Revision ID: b3e7f4a19c02
Revises: a7d21e6c8f30
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e7f4a19c02'
down_revision: Union[str, Sequence[str], None] = 'a7d21e6c8f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('mail_domains', sa.Column('stalwart_domain_id', sa.Text(), nullable=True))
    op.add_column('mail_domains', sa.Column('provisioning_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('mail_domains', 'provisioning_error')
    op.drop_column('mail_domains', 'stalwart_domain_id')
