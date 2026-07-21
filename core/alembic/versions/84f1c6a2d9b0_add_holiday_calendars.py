from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "84f1c6a2d9b0"
down_revision: Union[str, Sequence[str], None] = "72d84b91c3ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("holiday_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("workspaces", sa.Column("holiday_provider", sa.String(length=32), nullable=True))
    op.add_column("workspaces", sa.Column("holiday_country", sa.String(length=2), nullable=True))
    op.add_column("workspaces", sa.Column("holiday_region", sa.String(length=80), nullable=True))
    op.add_column("workspaces", sa.Column("holiday_city", sa.String(length=120), nullable=True))
    op.add_column("calendars", sa.Column("source", sa.String(length=40), nullable=True))
    op.create_unique_constraint("uq_calendars_workspace_source", "calendars", ["workspace_id", "source"])
    op.add_column("events", sa.Column("external_id", sa.String(length=240), nullable=True))
    op.create_unique_constraint("uq_events_calendar_external_id", "events", ["calendar_id", "external_id"])


def downgrade() -> None:
    op.drop_constraint("uq_events_calendar_external_id", "events", type_="unique")
    op.drop_column("events", "external_id")
    op.drop_constraint("uq_calendars_workspace_source", "calendars", type_="unique")
    op.drop_column("calendars", "source")
    op.drop_column("workspaces", "holiday_city")
    op.drop_column("workspaces", "holiday_region")
    op.drop_column("workspaces", "holiday_country")
    op.drop_column("workspaces", "holiday_provider")
    op.drop_column("workspaces", "holiday_enabled")
