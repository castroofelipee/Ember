"""Background-job application (Procrastinate).

A single `App` is the entry point for both deferring jobs (from the API process)
and running them (from the worker process). Procrastinate is Postgres-native:
it stores its queue in the app's own database and uses LISTEN/NOTIFY for wakeups
— no Redis or extra broker to run, which suits Ember's self-hosted model. See
docs/background-jobs.md for the rationale.

Construction does no I/O; the connection pool opens only when the app is
`open`ed (in the worker) or a job is deferred. Task modules are listed in
`import_paths` so the worker discovers them at startup.
"""

from procrastinate import App, PsycopgConnector

from ember.config import psycopg_dsn

app = App(
    connector=PsycopgConnector(conninfo=psycopg_dsn()),
    import_paths=["ember.jobs.tasks"],
)
