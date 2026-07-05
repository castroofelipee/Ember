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


class MailDomainNotProvisionedError(MailClientError):
    """The address's domain has no matching Domain object on the mail server.

    Ember's own MailDomain rows are not mirrored to Stalwart automatically yet
    (docs/rfc/mail-module.md §5 — tech debt), so a domain can exist in Ember
    while never having been created on the mail server. Provisioning an account
    on it must fail with a clear, actionable message rather than a generic
    provider error."""


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

    # Stalwart v0.16 removed the REST management API entirely: every management
    # action (Account, Domain, …) is now a JMAP object served from the same
    # `/jmap` endpoint as mail, reached with a `methodCalls` / `using` envelope
    # (https://stalw.art/blog/stalwart-0-16/). Account provisioning uses the
    # `x:Account/set` method under the `urn:stalwart:jmap` capability — distinct
    # from reading mail over JMAP (Email/Mailbox), which stays out of scope
    # (docs/rfc/mail-module.md §5).
    _JMAP_PATH = "/jmap"
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
        # A JMAP `Core/echo` (RFC 8620 §4) round-trips through the exact `/jmap`
        # endpoint account provisioning uses, proving both connectivity and that
        # the token authenticates — without depending on any particular object
        # existing. `_call_jmap` maps transport/timeout/401/403 to the right
        # error subclasses; a well-formed 2xx here is enough to return True.
        body = {
            "methodCalls": [["Core/echo", {"ember": "health_check"}, "c1"]],
            "using": ["urn:ietf:params:jmap:core"],
        }
        await self._call_jmap(body)
        return True

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
                f"""HTTP {response.status_code} URL: {response.request.url} Body: {response.text}"""
            )
        return response.json()

    @staticmethod
    def _unwrap_response(response_body: dict, method_name: str) -> dict:
        """Return the `arguments` object of the single call's response (a JMAP
        method call always answers `[name, arguments, tag]`; RFC 8620 §3.2),
        raising `MailClientError` for anything but a well-formed `method_name`
        response. Shared by the query/get/set callers below."""
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

    async def _resolve_domain_id(self, domain: str) -> str:
        """Look up the mail server's opaque Id for a Domain by its name.

        Stalwart keys accounts by a Domain object's server-assigned Id, not the
        domain name (an `x:Account/set` with the bare name fails with
        `invalidPatch: Failed to parse Id`). `x:Domain/query` filters by name
        (RFC 8620 §5.5); the returned id is what `domainId` must carry."""
        query_body = {
            "methodCalls": [["x:Domain/query", {"filter": {"name": domain}}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
        }
        arguments = self._unwrap_response(await self._call_jmap(query_body), "x:Domain/query")
        ids = arguments.get("ids") or []
        if not ids:
            raise MailDomainNotProvisionedError(
                f"Domain {domain!r} is not set up on the mail server; create it there "
                f"before provisioning accounts on it."
            )
        if len(ids) == 1:
            return str(ids[0])

        # A name filter can match more than one domain (e.g. a substring match);
        # disambiguate to the exact name via x:Domain/get.
        get_body = {
            "methodCalls": [["x:Domain/get", {"ids": ids}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
        }
        get_args = self._unwrap_response(await self._call_jmap(get_body), "x:Domain/get")
        for obj in get_args.get("list") or []:
            if str(obj.get("name", "")).lower() == domain.lower():
                return str(obj["id"])
        raise MailDomainNotProvisionedError(
            f"Mail server returned no exact match for domain {domain!r}."
        )

    async def create_account(
        self, address: str, password: str, *, quota_bytes: int | None = None
    ) -> MailAccount:
        local_part, _, domain = address.partition("@")
        if not local_part or not domain:
            raise ValueError(f"create_account requires a full address, got {address!r}")

        # Stalwart references the domain by its server-assigned Id, not its name,
        # so resolve it first (see _resolve_domain_id).
        domain_id = await self._resolve_domain_id(domain)

        create_fields = {
            "@type": "User",
            "name": local_part,
            "domainId": domain_id,

            "credentials": {
                "@type": "Password",
                "secret": password
            },

            "roles": {
                "@type": "User"
            },

            "permissions": {
                "@type": "Inherit"
            },

            "encryptionAtRest": {
                "@type": "Disabled"
            },

            "aliases": [],
            "memberGroupIds": [],
        }
        body = {
            "methodCalls": [["x:Account/set", {"create": {self._CREATE_KEY: create_fields}}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"],
        }

        response_body = await self._call_jmap(body)
        arguments = self._unwrap_response(response_body, "x:Account/set")

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
        arguments = self._unwrap_response(response_body, "x:Account/set")

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
