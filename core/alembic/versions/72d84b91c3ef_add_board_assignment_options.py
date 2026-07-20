from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "72d84b91c3ef"
down_revision: Union[str, Sequence[str], None] = "554f441b34c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("label_options", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    op.add_column(
        "boards",
        sa.Column("assignee_options", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("boards", "assignee_options")
    op.drop_column("boards", "label_options")
