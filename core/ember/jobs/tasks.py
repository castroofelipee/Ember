"""Background-job task definitions.

Tasks are plain async functions registered on the shared `app`. Any module
(Calendar, Mail, Notes, ...) will add its own tasks here (or in its own module
imported via the app's `import_paths`). For now there is only `example_job`,
which exists solely to validate that the pipeline — defer, queue, worker,
execute — works end to end.
"""

import logging

from ember.jobs.app import app

logger = logging.getLogger(__name__)


@app.task(name="example_job")
async def example_job(*, message: str = "hello") -> str:
    """No-op task proving the job pipeline runs. Real tasks follow this shape:
    an async function decorated with `@app.task`, deferred with
    `example_job.defer_async(...)`. Returns the message so tests can assert the
    worker executed it."""
    logger.info("example_job executed: %s", message)
    return message
