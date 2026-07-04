"""Provider-agnostic mail-server client.

Ember never speaks SMTP/IMAP itself (see docs/rfc/mail-module.md §3); it
delegates to a dedicated mail server and talks to it through this narrow
interface. `MailClient` is the seam every provider implements; keeping the rest
of the app behind it means the backend (Stalwart today, something else later)
is swappable without touching domain code.

`health_check`, `create_account`, and `delete_account` are wired to a real
backend so far. Password rotation remains an unimplemented stub.
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


class MailAccountAlreadyExistsError(MailClientError):
    """The requested address is already taken on the mail server."""


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
    `health_check`, `create_account`, and `delete_account` are implemented;
    password rotation still raises `NotImplementedError`.
    """

    # Lightweight admin-only endpoint: a successful GET proves both connectivity
    # and that the token authenticates as an administrator. `limit=1` keeps the
    # response minimal — we only care about the status code.
    _HEALTH_PATH = "/api/principal"

    # Account provisioning goes through Stalwart's current management surface:
    # a single JMAP-envelope endpoint (`methodCalls` / `using`), not the legacy
    # per-object REST routes `_HEALTH_PATH` uses. This is Stalwart's own admin
    # object model (`x:Account/set`, capability `urn:stalwart:jmap`) — distinct
    # from reading mail over JMAP (Email/Mailbox), which stays out of scope
    # (docs/rfc/mail-module.md §5; verified against stalw.art/docs/ref/object/account/).
    _JMAP_PATH = "/api"
    _CREATE_KEY = "new1"

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

    async def _call_jmap(self, body: dict) -> dict:
        """POST a JMAP request envelope to Stalwart's management endpoint and
        return the decoded response body. Raises the same `MailClientError`
        subclasses as `health_check` for transport/timeout/auth failures."""
        headers = {
            "Authorization": f"Bearer {self._admin_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(self._JMAP_PATH, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise MailTimeoutError(
                f"Mail server did not respond within {self._timeout}s at {self._base_url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MailConnectionError(
                f"Could not reach mail server at {self._base_url}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise MailAuthenticationError(
                f"Mail server rejected admin credentials (HTTP {response.status_code})"
            )
        if not response.is_success:
            raise MailClientError(
                f"Unexpected response from mail server: HTTP {response.status_code}"
            )
        return response.json()

    @staticmethod
    def _unwrap_set_response(response_body: dict, method_name: str) -> dict:
        """Return the `arguments` object of the single call's response (JMAP core
        `/set` methods always answer `[name, arguments, tag]`; RFC 8620 §3.2),
        raising `MailClientError` for anything but a well-formed `method_name`
        response. Shared by every `x:Account/set` caller below."""
        method_responses = response_body.get("methodResponses") or []
        if not method_responses:
            raise MailClientError(f"Mail server returned no methodResponses for {method_name}")

        name, arguments = method_responses[0][0], method_responses[0][1]
        if name == "error":
            raise MailClientError(
                f"Mail server rejected {method_name}: {arguments.get('type')} "
                f"({arguments.get('description', 'no description')})"
            )
        return arguments

    async def create_account(
        self, address: str, password: str, *, quota_bytes: int | None = None
    ) -> MailAccount:
        local_part, _, domain = address.partition("@")
        if not local_part or not domain:
            raise ValueError(f"create_account requires a full address, got {address!r}")

        # Stalwart keys a Domain object by its domain name (docs/rfc/mail-module.md
        # §5 — Ember's own MailDomain likewise stores the bare domain, no separate
        # provider-side domain id), so the address's domain part doubles as
        # `domainId` here without a prior lookup.
        create_fields = {
            "@type": "User",
            "name": local_part,
            "domainId": domain,
            "credentials": [{"@type": "Password", "secret": password}],
            "roles": {"@type": "User"},
            "permissions": {"@type": "Inherit"},
            "encryptionAtRest": {"@type": "Disabled"},
            "quotas": {"maxDiskQuota": quota_bytes} if quota_bytes is not None else {},
            "aliases": [],
            "memberGroupIds": [],
        }
        body = {
            "methodCalls": [
                ["x:Account/set", {"create": {self._CREATE_KEY: create_fields}}, "c1"]
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
        }

        response_body = await self._call_jmap(body)
        arguments = self._unwrap_set_response(response_body, "x:Account/set")

        not_created = arguments.get("notCreated") or {}
        if self._CREATE_KEY in not_created:
            error = not_created[self._CREATE_KEY]
            description = error.get("description", "no description")
            if error.get("type") == "alreadyExists":
                raise MailAccountAlreadyExistsError(
                    f"Account {address!r} already exists on the mail server: {description}"
                )
            raise MailClientError(
                f"Mail server refused to create account {address!r}: "
                f"{error.get('type')} ({description})"
            )

        created = (arguments.get("created") or {}).get(self._CREATE_KEY)
        if created is None:
            raise MailClientError(
                f"Mail server response for x:Account/set had neither created nor "
                f"notCreated for {address!r}"
            )
        return MailAccount(id=str(created["id"]), address=created.get("emailAddress", address))

    async def set_password(self, account_id: str, password: str) -> None:
        raise NotImplementedError("Stalwart password rotation is not implemented yet")

    async def delete_account(self, account_id: str) -> None:
        # Same `x:Account/set` method as create, using its `destroy` argument
        # instead of `create` (RFC 8620 §5.3): a list of ids to remove, echoed
        # back as `destroyed` on success or `notDestroyed` keyed by id on failure.
        body = {
            "methodCalls": [["x:Account/set", {"destroy": [account_id]}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
        }

        response_body = await self._call_jmap(body)
        arguments = self._unwrap_set_response(response_body, "x:Account/set")

        not_destroyed = arguments.get("notDestroyed") or {}
        if account_id in not_destroyed:
            error = not_destroyed[account_id]
            raise MailClientError(
                f"Mail server refused to delete account {account_id!r}: "
                f"{error.get('type')} ({error.get('description', 'no description')})"
            )

        destroyed = arguments.get("destroyed") or []
        if account_id not in destroyed:
            raise MailClientError(
                f"Mail server response for x:Account/set had neither destroyed nor "
                f"notDestroyed for {account_id!r}"
            )
