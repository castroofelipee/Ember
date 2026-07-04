# Background Jobs

Status: implemented — base infrastructure only. One example task; no
module-specific jobs yet.

Stack: FastAPI + SQLAlchemy (async) + PostgreSQL, plus **Procrastinate** as the
job queue.

## Why Procrastinate

Ember needs durable background work (per `docs/rfc/mail-module.md` §9: send,
retry, sync, indexing) that outlives a single HTTP request. Requirements:

- Durable — a job survives a process restart; not `FastAPI BackgroundTasks`,
  which run in-process and vanish on crash.
- Async-native — fits the existing async SQLAlchemy / FastAPI code.
- **No new infrastructure** — Ember is self-hosted; adding Redis or RabbitMQ
  means one more service to run, back up, and secure. The deploy today is
  "api + web + external Postgres"; the job queue should not change that shape.

**Procrastinate** meets all three: it stores its queue in the app's own
PostgreSQL and uses `LISTEN/NOTIFY` for low-latency wakeups — no broker. It is
async-first (`defer_async`, `run_worker_async`), ships retries, scheduling, and
a worker CLI, and is testable in-memory. This is the choice the mail RFC already
argued for.

Rejected alternatives: Celery/Dramatiq/arq (require Redis or RabbitMQ — extra
infrastructure); FastAPI `BackgroundTasks` (not durable); a hand-rolled
Postgres queue (reinvents locking/retries/scheduling for no gain over
Procrastinate).

## Shape

```
core/ember/jobs/
├── __init__.py   # public surface: `app`, `example_job`
├── app.py        # the Procrastinate App (connector from config.psycopg_dsn())
└── tasks.py      # @app.task definitions; example_job for now
```

- **One `App`, two roles.** The api process imports `app` to *defer* jobs; the
  worker process runs `app` to *execute* them. Construction does no I/O — the
  connection pool opens lazily.
- **Same database.** The connector uses `config.psycopg_dsn()` — the app's
  Postgres with a plain psycopg DSN (no SQLAlchemy `+psycopg` tag).
- **Schema via Alembic.** Procrastinate's tables are installed by migration
  `e1a7c0b93f52`, which applies `SchemaManager.get_schema()`. This runs in the
  same `alembic upgrade head` the api container already executes on deploy, and
  exactly once (the schema itself is not idempotent).
- **Worker service.** `docker-compose.yml` adds a `worker` service:
  `procrastinate --app=ember.jobs.app.app worker`. It shares the api's image
  and database and depends on the api (which applies the schema).

## Defining and deferring a job

```python
# in ember/jobs/tasks.py (or a module's own tasks file listed in App.import_paths)
@app.task(name="example_job")
async def example_job(*, message: str = "hello") -> str:
    ...

# anywhere in the api
from ember.jobs import example_job
await example_job.defer_async(message="hi")
```

Any module (Calendar, Mail, Notes, Drive) adds its own `@app.task` functions the
same way. There are intentionally **no** module-specific jobs yet.

## Testing

Procrastinate's `testing.InMemoryConnector` replaces Postgres, so the full
defer → queue → execute pipeline is asserted without a database or a running
worker (`tests/test_jobs.py`):

```python
connector = testing.InMemoryConnector()
with app.replace_connector(connector):
    await example_job.defer_async(message="hi")
    await app.run_worker_async(wait=False, install_signal_handlers=False, listen_notify=False)
assert list(connector.jobs.values())[0]["status"] == "succeeded"
```

## Operational notes / known debt

- **Deferring opens a pool.** Calling `defer_async` from the api opens
  Procrastinate's own psycopg pool (separate from SQLAlchemy's engine). Its
  lifecycle (open on startup / close on shutdown via `app.open_async`) should be
  wired into the FastAPI lifespan when the first real producer lands. Not needed
  yet — nothing defers in the request path today.
- **Transactional enqueue.** For "never lose a job" semantics, a job should be
  deferred in the same transaction as the domain write that triggers it.
  Procrastinate supports this; the pattern will be adopted when a real producer
  exists.
- **Schema upgrades.** Future Procrastinate versions ship migration deltas;
  bumping the dependency means adding the corresponding Alembic migration, not
  re-applying the full schema.
