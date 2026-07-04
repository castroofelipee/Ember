"""Tests for the background-job infrastructure (docs/background-jobs.md).

No real database or worker process: Procrastinate's in-memory connector stands
in for Postgres so we can assert the full defer → queue → execute pipeline
deterministically and fast.
"""

from procrastinate import testing

from ember.jobs import app, example_job


async def test_example_job_is_queued_on_defer() -> None:
    connector = testing.InMemoryConnector()
    with app.replace_connector(connector):
        await example_job.defer_async(message="hi")

    jobs = list(connector.jobs.values())
    assert len(jobs) == 1
    assert jobs[0]["task_name"] == "example_job"
    assert jobs[0]["args"] == {"message": "hi"}
    assert jobs[0]["status"] == "todo"


async def test_worker_executes_example_job() -> None:
    connector = testing.InMemoryConnector()
    with app.replace_connector(connector):
        await example_job.defer_async(message="run me")
        # wait=False drains the queue once and returns instead of blocking.
        await app.run_worker_async(
            wait=False, install_signal_handlers=False, listen_notify=False
        )

    assert list(connector.jobs.values())[0]["status"] == "succeeded"


async def test_example_job_returns_message() -> None:
    # The task is a plain async function; calling it directly exercises its body
    # without the queue.
    assert await example_job.func(message="pong") == "pong"
