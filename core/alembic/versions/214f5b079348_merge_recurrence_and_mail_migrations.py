"""merge recurrence and mail migrations

Revision ID: 214f5b079348
Revises: 3b5750ee264b, a1f3c9d20b84
Create Date: 2026-07-04 19:35:10.529466

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '214f5b079348'
down_revision: Union[str, Sequence[str], None] = ('3b5750ee264b', 'a1f3c9d20b84')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
