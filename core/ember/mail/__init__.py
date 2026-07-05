"""Mail module — base infrastructure.

Public surface for the mail provider abstraction. No endpoints, models, or mail
server integration yet (docs/rfc/mail-module.md): this package currently only
defines the client seam and how to obtain a configured instance.
"""

from ember.config import env, mail_enabled
from ember.mail.client import (
    MailAccount,
    MailAccountAlreadyExistsError,
    MailAuthenticationError,
    MailClient,
    MailClientError,
    MailConnectionError,
    MailDomainNotProvisionedError,
    MailSendResult,
    MailTimeoutError,
    StalwartMailClient,
)

__all__ = [
    "MailAccount",
    "MailAccountAlreadyExistsError",
    "MailAuthenticationError",
    "MailClient",
    "MailClientError",
    "MailConnectionError",
    "MailDomainNotProvisionedError",
    "MailSendResult",
    "MailTimeoutError",
    "StalwartMailClient",
    "get_mail_client",
]


def get_mail_client() -> MailClient | None:
    """Build the configured mail client, or None when mail is disabled.

    Returning None (rather than raising) keeps mail strictly optional: Ember
    runs identically with no mail server configured, which is the default. When
    enabled, the concrete backend is chosen here — the single place that knows
    which provider is in use.
    """
    if not mail_enabled():
        return None
    return StalwartMailClient(
        base_url=env["MAIL_SERVER_URL"],
        admin_token=env["MAIL_ADMIN_TOKEN"],
        timeout=float(env["MAIL_HTTP_TIMEOUT_SECONDS"]),
    )
