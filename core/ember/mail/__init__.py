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
    MailMessageDetail,
    MailMessageUpdate,
    MailMessageSummary,
    MailAddress,
    MailboxInfo,
    MailDomainNotProvisionedError,
    MailSendResult,
    MailTimeoutError,
    StalwartMailClient,
)
from ember.mail.sender import MailSender, ResendMailSender, StalwartMailSender

__all__ = [
    "MailAccount",
    "MailAccountAlreadyExistsError",
    "MailAuthenticationError",
    "MailClient",
    "MailClientError",
    "MailConnectionError",
    "MailMessageDetail",
    "MailMessageUpdate",
    "MailMessageSummary",
    "MailAddress",
    "MailboxInfo",
    "MailDomainNotProvisionedError",
    "MailSendResult",
    "MailTimeoutError",
    "StalwartMailClient",
    "get_mail_client",
    "MailSender",
    "ResendMailSender",
    "StalwartMailSender",
    "get_mail_sender",
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


def get_mail_sender(mail_client: MailClient | None = None) -> MailSender | None:
    """Build the independently configured outbound provider."""
    # An explicitly injected client is also the test/custom-deployment seam;
    # the normal disabled path calls this without one and remains None.
    if not mail_enabled() and mail_client is None:
        return None
    client = mail_client or get_mail_client()
    provider = env["MAIL_OUTBOUND_PROVIDER"].strip().lower()
    if provider == "stalwart":
        if client is None:  # Defensive: MAIL_ENABLED guarantees one today.
            return None
        return StalwartMailSender(client)
    if provider == "resend":
        return ResendMailSender(
            env["RESEND_API_KEY"],
            timeout=float(env["RESEND_TIMEOUT_SECONDS"]),
            mailbox_client=client,
        )
    raise ValueError(f"Unsupported MAIL_OUTBOUND_PROVIDER: {provider!r}")
