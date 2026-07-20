"""Outbound-only mail provider abstraction."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence

import httpx

from ember.mail.client import (
    MailAuthenticationError,
    MailClient,
    MailClientError,
    MailConnectionError,
    MailSendResult,
    MailTimeoutError,
)

logger = logging.getLogger(__name__)


class MailSender(ABC):
    @abstractmethod
    async def send_message(
        self,
        *,
        account_id: str,
        from_address: str,
        to: Sequence[str],
        subject: str,
        text: str,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
    ) -> MailSendResult:
        """Deliver one plain-text email."""


class StalwartMailSender(MailSender):
    """Compatibility adapter around Stalwart's existing JMAP submission."""

    def __init__(self, mail_client: MailClient) -> None:
        self._mail_client = mail_client

    async def send_message(self, **kwargs) -> MailSendResult:
        return await self._mail_client.send_message(**kwargs)


class ResendMailSender(MailSender):
    _API_URL = "https://api.resend.com/emails"
    _USER_AGENT = "Ember/1.0"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 10.0,
        mailbox_client: MailClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ResendMailSender requires a non-empty api_key")
        self._api_key = api_key
        self._timeout = timeout
        self._mailbox_client = mailbox_client
        self._transport = transport

    async def send_message(
        self,
        *,
        account_id: str,
        from_address: str,
        to: Sequence[str],
        subject: str,
        text: str,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
    ) -> MailSendResult:
        payload: dict = {
            "from": from_address,
            "to": list(to),
            "subject": subject,
            "text": text,
        }
        if cc:
            payload["cc"] = list(cc)
        if bcc:
            payload["bcc"] = list(bcc)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    self._API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": self._USER_AGENT,
                    },
                )
        except httpx.TimeoutException as exc:
            raise MailTimeoutError(f"Resend did not respond within {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise MailConnectionError(f"Could not reach Resend: {exc}") from exc

        if response.status_code in (401, 403):
            raise MailAuthenticationError(
                "Resend rejected outbound authorization "
                f"(HTTP {response.status_code}): {self._error_detail(response)}"
            )
        if not response.is_success:
            raise MailClientError(
                f"Resend rejected send request (HTTP {response.status_code}): {response.text}"
            )
        try:
            provider_id = str(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise MailClientError("Resend returned no email id") from exc

        if self._mailbox_client is not None:
            try:
                await self._mailbox_client.save_sent_message(
                    account_id=account_id,
                    from_address=from_address,
                    to=to,
                    cc=cc,
                    bcc=bcc,
                    subject=subject,
                    text=text,
                )
            except (MailClientError, NotImplementedError) as exc:
                logger.error(
                    "Resend delivered email %s but Stalwart Sent copy failed: %s",
                    provider_id,
                    exc,
                )
        return MailSendResult(email_id=provider_id, submission_id=provider_id)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text or "no response body"
        if isinstance(body, dict):
            for key in ("message", "error", "name"):
                value = body.get(key)
                if value:
                    return str(value)
        return response.text or "no response body"
