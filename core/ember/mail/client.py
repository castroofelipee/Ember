"""Provider-agnostic mail-server client.

Ember never speaks SMTP/IMAP itself (see docs/rfc/mail-module.md §3); it
delegates to a dedicated mail server and talks to it through this narrow
interface. `MailClient` is the seam every provider implements; keeping the rest
of the app behind it means the backend (Stalwart today, something else later)
is swappable without touching domain code.

Only `health_check` is wired to a real backend so far — enough to confirm the
server is reachable and the admin credentials are accepted. Provisioning,
password rotation, and deletion remain unimplemented stubs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


class MailClientError(Exception):
    """Base error for mail-provider operations. Concrete clients raise this (or
    a subclass) so callers handle provider failures without depending on a
    specific backend's exception types."""


class MailConnectionError(MailClientError):
    """The mail server could not be reached (DNS, refused connection, transport
    failure)."""


class MailTimeoutError(MailClientError):
    """The mail server did not respond within the configured timeout."""


class MailAuthenticationError(MailClientError):
    """The mail server rejected the admin credentials, or the authenticated
    principal lacks the permissions the operation requires."""


@dataclass(frozen=True)
class MailAccount:
    id: str
    address: str


class MailClient(ABC):
    """Abstraction over a mail server's management surface. Only account
    lifecycle is modeled for now; message read/send (JMAP) comes later."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True when the mail server is reachable and the admin
        credentials are accepted. Raises a `MailClientError` subclass on
        connection, timeout, or authentication failures."""

    @abstractmethod
    async def create_account(
        self, address: str, password: str, *, quota_bytes: int | None = None
    ) -> MailAccount:
        """Provision a new mailbox account for `address`."""

    @abstractmethod
    async def set_password(self, account_id: str, password: str) -> None:
        """Rotate the password of an existing account."""

    @abstractmethod
    async def delete_account(self, account_id: str) -> None:
        """Permanently remove an account and its mailboxes."""


class StalwartMailClient(MailClient):
    """`MailClient` backed by a Stalwart mail server (docs/rfc/mail-module.md
    §2), reached over its REST management API.

    Authentication is a Bearer token (`admin_token`) — Stalwart's management
    endpoints accept an API key / access token in the `Authorization` header.
    Only `health_check` is implemented; the other operations still raise
    `NotImplementedError`.
    """

    # Lightweight admin-only endpoint: a successful GET proves both connectivity
    # and that the token authenticates as an administrator. `limit=1` keeps the
    # response minimal — we only care about the status code.
    _HEALTH_PATH = "/api/principal"

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("StalwartMailClient requires a non-empty base_url")
        # Normalize once so callers can join paths without worrying about a
        # trailing slash.
        self._base_url = base_url.rstrip("/")
        self._admin_token = admin_token
        self._timeout = timeout
        # Injectable transport is a test seam (httpx.MockTransport); None uses
        # httpx's real network transport in production.
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    async def health_check(self) -> bool:
        headers = {
            "Authorization": f"Bearer {self._admin_token}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    self._HEALTH_PATH, params={"limit": 1}, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise MailTimeoutError(
                f"Mail server did not respond within {self._timeout}s at {self._base_url}"
            ) from exc
        except httpx.HTTPError as exc:
            # Covers connection refused, DNS failures, and other transport errors.
            raise MailConnectionError(
                f"Could not reach mail server at {self._base_url}: {exc}"
            ) from exc

        # 401: token invalid/expired. 403: authenticated but not an admin. Both
        # mean the configured credentials cannot manage the server.
        if response.status_code in (401, 403):
            raise MailAuthenticationError(
                f"Mail server rejected admin credentials (HTTP {response.status_code})"
            )
        if response.is_success:
            return True
        raise MailClientError(
            f"Unexpected response from mail server: HTTP {response.status_code}"
        )

    async def create_account(
        self, address: str, password: str, *, quota_bytes: int | None = None
    ) -> MailAccount:
        raise NotImplementedError("Stalwart account provisioning is not implemented yet")

    async def set_password(self, account_id: str, password: str) -> None:
        raise NotImplementedError("Stalwart password rotation is not implemented yet")

    async def delete_account(self, account_id: str) -> None:
        raise NotImplementedError("Stalwart account deletion is not implemented yet")
