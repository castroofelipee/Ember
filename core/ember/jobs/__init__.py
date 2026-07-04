"""Background jobs — generic, reusable infrastructure for any Ember module.

Powered by Procrastinate (Postgres-native queue). Import `app` to defer jobs or
to point the worker at it (`procrastinate --app=ember.jobs.app.app worker`), and
`example_job` as the reference task. No module-specific jobs live here.
"""

from ember.jobs.app import app
from ember.jobs.tasks import example_job

__all__ = ["app", "example_job"]
