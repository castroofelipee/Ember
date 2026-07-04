"""add procrastinate (background jobs) schema

Installs the Procrastinate queue schema (tables, types, functions, triggers)
that the background-job infrastructure needs. The SQL is owned and versioned by
Procrastinate itself; we apply it through Alembic so it lands in the same
`alembic upgrade head` step the api container already runs on deploy, and so it
is applied exactly once (Alembic tracks it) — the schema is not idempotent, so
re-running it directly would fail.

Revision ID: e1a7c0b93f52
Revises: d5c9a1f4e2b7
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from procrastinate.schema import SchemaManager

# revision identifiers, used by Alembic.
revision: str = 'e1a7c0b93f52'
down_revision: Union[str, Sequence[str], None] = 'd5c9a1f4e2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply Procrastinate's bundled schema for the installed version."""
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    """Drop everything Procrastinate created. All of its objects are prefixed
    `procrastinate_`; CASCADE clears dependent indexes/triggers, and the loop
    removes the functions (which vary by version)."""
    op.execute(
        """
        DO $$
        DECLARE
            obj record;
        BEGIN
            FOR obj IN
                SELECT p.oid::regprocedure AS sig
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate_%'
            LOOP
                EXECUTE 'DROP FUNCTION IF EXISTS ' || obj.sig || ' CASCADE';
            END LOOP;
        END $$;

        DROP TABLE IF EXISTS procrastinate_events CASCADE;
        DROP TABLE IF EXISTS procrastinate_periodic_defers CASCADE;
        DROP TABLE IF EXISTS procrastinate_jobs CASCADE;
        DROP TABLE IF EXISTS procrastinate_workers CASCADE;

        DROP TYPE IF EXISTS procrastinate_job_to_defer_v1 CASCADE;
        DROP TYPE IF EXISTS procrastinate_job_event_type CASCADE;
        DROP TYPE IF EXISTS procrastinate_job_status CASCADE;
        """
    )
