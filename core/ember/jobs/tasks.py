"""Background-job task definitions.

Tasks are plain async functions registered on the shared `app`. Any module
(Calendar, Mail, Notes, ...) will add its own tasks here (or in its own module
imported via the app's `import_paths`). For now there is only `example_job`,
which exists solely to validate that the pipeline — defer, queue, worker,
execute — works end to end.
"""

import logging
import uuid

from ember.db import async_session
from ember.jobs.app import app
from ember.mail import get_mail_client
from ember.models import MailDomain, MailDomainStatus

logger = logging.getLogger(__name__)


@app.task(name="example_job")
async def example_job(*, message: str = "hello") -> str:
    """No-op task proving the job pipeline runs. Real tasks follow this shape:
    an async function decorated with `@app.task`, deferred with
    `example_job.defer_async(...)`. Returns the message so tests can assert the
    worker executed it."""
    logger.info("example_job executed: %s", message)
    return message


# Ceiling on `verify_domain_dns` self-reschedules (10s apart — see below) —
# about 5 minutes, generous for Cloudflare's usual sub-minute propagation
# without polling forever if something is actually stuck.
_VERIFY_DNS_MAX_ATTEMPTS = 30
_VERIFY_DNS_RETRY_SECONDS = 10


@app.task(name="verify_domain_dns")
async def verify_domain_dns(*, domain_id: str, attempt: int = 1) -> str:
    """Poll the mail server's DNS-management task for `domain_id` until it
    settles, then reflect the outcome on the `MailDomain` row.

    Runs in the worker, so it builds its own mail client and DB session
    rather than depending on request-scoped ones (docs/background-jobs.md).
    Self-reschedules while the publish is still in flight — Procrastinate has
    no built-in "poll until done" primitive, and this keeps each run short and
    inspectable in the job table rather than sleeping inside one execution.
    """
    mail_client = get_mail_client()
    if mail_client is None:
        return "mail disabled"

    async with async_session() as session:
        domain = await session.get(MailDomain, uuid.UUID(domain_id))
        if domain is None or not domain.stalwart_domain_id:
            return "domain gone or never provisioned"

        status = await mail_client.get_dns_publish_status(domain.stalwart_domain_id)

        if status.state == "completed":
            domain.status = MailDomainStatus.ACTIVE
            domain.provisioning_error = None
            await session.commit()
            return "active"

        if status.state == "failed":
            domain.provisioning_error = status.failure_reason or "DNS publication failed"
            await session.commit()
            return "failed"

        # Still pending.
        if attempt >= _VERIFY_DNS_MAX_ATTEMPTS:
            domain.provisioning_error = (
                "DNS records are still publishing on the mail server after "
                f"{_VERIFY_DNS_MAX_ATTEMPTS * _VERIFY_DNS_RETRY_SECONDS}s; check Stalwart directly."
            )
            await session.commit()
            return "gave up"

    await verify_domain_dns.configure(
        schedule_in={"seconds": _VERIFY_DNS_RETRY_SECONDS}
    ).defer_async(domain_id=domain_id, attempt=attempt + 1)
    return "pending"
