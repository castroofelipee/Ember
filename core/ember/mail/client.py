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
from collections.abc import Sequence
from datetime import UTC, datetime

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


@dataclass(frozen=True)
class MailSendResult:
    email_id: str
    submission_id: str


@dataclass(frozen=True)
class MailAddress:
    email: str
    name: str | None = None


@dataclass(frozen=True)
class MailboxInfo:
    id: str
    name: str
    role: str | None
    total_emails: int
    total_threads: int
    unread_emails: int
    unread_threads: int


@dataclass(frozen=True)
class MailMessageSummary:
    id: str
    thread_id: str
    mailbox_ids: tuple[str, ...]
    keywords: tuple[str, ...]
    has_attachment: bool
    sender: MailAddress | None
    subject: str
    preview: str
    received_at: datetime
    size: int


@dataclass(frozen=True)
class MailMessageDetail:
    id: str
    thread_id: str
    mailbox_ids: tuple[str, ...]
    keywords: tuple[str, ...]
    has_attachment: bool
    sender: MailAddress | None
    to: tuple[MailAddress, ...]
    cc: tuple[MailAddress, ...]
    bcc: tuple[MailAddress, ...]
    reply_to: tuple[MailAddress, ...]
    subject: str
    preview: str
    received_at: datetime
    size: int
    text_body: str
    html_body: str


@dataclass(frozen=True)
class MailMessageUpdate:
    seen: bool | None = None
    flagged: bool | None = None
    mailbox_role: str | None = None


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
        """Create and submit a text email through the provider."""

    async def save_sent_message(
        self,
        *,
        account_id: str,
        from_address: str,
        to: Sequence[str],
        subject: str,
        text: str,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
    ) -> str:
        """Store an already-delivered message in Sent without submitting it."""
        raise NotImplementedError

    @abstractmethod
    async def list_mailboxes(self, *, account_id: str) -> Sequence[MailboxInfo]:
        """List mailboxes for an account."""

    @abstractmethod
    async def list_messages(
        self,
        *,
        account_id: str,
        mailbox_role: str,
        limit: int = 50,
        collapse_threads: bool = True,
    ) -> Sequence[MailMessageSummary]:
        """List messages or collapsed threads for a mailbox role."""

    @abstractmethod
    async def get_message(self, *, account_id: str, message_id: str) -> MailMessageDetail:
        """Fetch one message in detail."""

    @abstractmethod
    async def update_message(
        self, *, account_id: str, message_id: str, patch: MailMessageUpdate
    ) -> MailMessageDetail:
        """Update message flags or mailbox placement."""

    @abstractmethod
    async def mark_mailbox_read(self, *, account_id: str, mailbox_role: str) -> int:
        """Mark every unread message in a mailbox role as read.

        Returns the number of messages whose `$seen` flag was set."""

    @abstractmethod
    async def list_thread_messages(
        self, *, account_id: str, thread_id: str
    ) -> Sequence[MailMessageDetail]:
        """Fetch all messages in a thread."""


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
    _PASSWORD_CREDENTIAL_KEY = "0"
    _EMAIL_CREATE_KEY = "email1"
    _SUBMISSION_CREATE_KEY = "submission1"

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

    @staticmethod
    def _unwrap_tagged_response(response_body: dict, tag: str, method_name: str) -> dict:
        method_responses = response_body.get("methodResponses") or []
        for response in method_responses:
            name, arguments, response_tag = response
            if response_tag != tag:
                continue
            if name == "error":
                raise MailClientError(
                    f"Mail server rejected {method_name}: {arguments.get('type')} "
                    f"({arguments.get('description', 'no description')})"
                )
            if name == method_name:
                return arguments
        raise MailClientError(f"Mail server returned no {method_name} response for tag {tag}")

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
                self._PASSWORD_CREDENTIAL_KEY: {"@type": "Password", "secret": password}
            },
            "roles": {"@type": "User"},
            "permissions": {"@type": "Inherit"},
            "encryptionAtRest": {"@type": "Disabled"},
            "quotas": {},
            "aliases": {},
            "memberGroupIds": {},
        }
        if quota_bytes is not None:
            create_fields["quotas"] = {"maxDiskQuota": quota_bytes}
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

    async def _resolve_mailbox_ids_by_role(
        self, account_id: str, roles: Sequence[str]
    ) -> dict[str, str]:
        body = {
            "methodCalls": [["Mailbox/get", {"accountId": account_id, "ids": None}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        arguments = self._unwrap_response(await self._call_jmap(body), "Mailbox/get")
        wanted = set(roles)
        found: dict[str, str] = {}
        for mailbox in arguments.get("list") or []:
            role = mailbox.get("role")
            if role in wanted and role not in found:
                found[role] = str(mailbox["id"])
        missing = wanted - set(found)
        if missing:
            raise MailClientError(
                f"Mail server account {account_id!r} is missing mailbox role(s): "
                f"{', '.join(sorted(missing))}"
            )
        return found

    @staticmethod
    def _mail_address(data: dict | None) -> MailAddress | None:
        if not data:
            return None
        email = str(data.get("email", "")).strip()
        if not email:
            return None
        name = data.get("name")
        return MailAddress(email=email, name=None if name in (None, "") else str(name))

    @classmethod
    def _mail_addresses(cls, values: Sequence[dict] | None) -> tuple[MailAddress, ...]:
        return tuple(
            address for address in (cls._mail_address(value) for value in (values or ())) if address
        )

    @staticmethod
    def _parse_received_at(value: str) -> datetime:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _body_value(parts: Sequence[dict] | None, body_values: dict | None) -> str:
        body_values = body_values or {}
        chunks: list[str] = []
        for part in parts or ():
            part_id = str(part.get("partId", ""))
            if not part_id:
                continue
            value = body_values.get(part_id, {})
            text = value.get("value")
            if isinstance(text, str) and text:
                chunks.append(text)
        return "\n\n".join(chunks).strip()

    def _message_summary(self, email: dict) -> MailMessageSummary:
        sender = self._mail_address((email.get("from") or [None])[0])
        return MailMessageSummary(
            id=str(email["id"]),
            thread_id=str(email["threadId"]),
            mailbox_ids=tuple(
                str(mailbox_id) for mailbox_id in (email.get("mailboxIds") or {}).keys()
            ),
            keywords=tuple(
                sorted(
                    str(keyword)
                    for keyword, enabled in (email.get("keywords") or {}).items()
                    if enabled
                )
            ),
            has_attachment=bool(email.get("hasAttachment", False)),
            sender=sender,
            subject=str(email.get("subject") or ""),
            preview=str(email.get("preview") or ""),
            received_at=self._parse_received_at(str(email["receivedAt"])),
            size=int(email.get("size") or 0),
        )

    def _message_detail(self, email: dict) -> MailMessageDetail:
        body_values = email.get("bodyValues") or {}
        return MailMessageDetail(
            id=str(email["id"]),
            thread_id=str(email["threadId"]),
            mailbox_ids=tuple(
                str(mailbox_id) for mailbox_id in (email.get("mailboxIds") or {}).keys()
            ),
            keywords=tuple(
                sorted(
                    str(keyword)
                    for keyword, enabled in (email.get("keywords") or {}).items()
                    if enabled
                )
            ),
            has_attachment=bool(email.get("hasAttachment", False)),
            sender=self._mail_address((email.get("from") or [None])[0]),
            to=self._mail_addresses(email.get("to")),
            cc=self._mail_addresses(email.get("cc")),
            bcc=self._mail_addresses(email.get("bcc")),
            reply_to=self._mail_addresses(email.get("replyTo")),
            subject=str(email.get("subject") or ""),
            preview=str(email.get("preview") or ""),
            received_at=self._parse_received_at(str(email["receivedAt"])),
            size=int(email.get("size") or 0),
            text_body=self._body_value(email.get("textBody"), body_values),
            html_body=self._body_value(email.get("htmlBody"), body_values),
        )

    async def _resolve_identity_id(self, account_id: str, from_address: str) -> str:
        body = {
            "methodCalls": [["Identity/get", {"accountId": account_id, "ids": None}, "c1"]],
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:ietf:params:jmap:mail",
                "urn:ietf:params:jmap:submission",
            ],
        }
        arguments = self._unwrap_response(await self._call_jmap(body), "Identity/get")
        identities = arguments.get("list") or []
        for identity in identities:
            if str(identity.get("email", "")).lower() == from_address.lower():
                return str(identity["id"])
        if identities:
            return str(identities[0]["id"])
        raise MailClientError(
            f"Mail server account {account_id!r} has no sending identity configured"
        )

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
        mailboxes = await self._resolve_mailbox_ids_by_role(account_id, ("drafts", "sent"))
        identity_id = await self._resolve_identity_id(account_id, from_address)

        def addresses(values: Sequence[str]) -> list[dict[str, str]]:
            return [{"email": value} for value in values]

        draft_id = mailboxes["drafts"]
        sent_id = mailboxes["sent"]
        create_email = {
            "mailboxIds": {draft_id: True},
            "keywords": {"$draft": True},
            "from": [{"email": from_address}],
            "to": addresses(to),
            "subject": subject,
            "bodyValues": {"body": {"value": text, "charset": "utf-8"}},
            "textBody": [{"partId": "body", "type": "text/plain"}],
        }
        if cc:
            create_email["cc"] = addresses(cc)
        if bcc:
            create_email["bcc"] = addresses(bcc)

        envelope_recipients = addresses([*to, *cc, *bcc])
        envelope = {
            "mailFrom": {"email": from_address, "parameters": None},
            "rcptTo": [
                {"email": recipient["email"], "parameters": None}
                for recipient in envelope_recipients
            ],
        }
        body = {
            "methodCalls": [
                [
                    "Email/set",
                    {"accountId": account_id, "create": {self._EMAIL_CREATE_KEY: create_email}},
                    "c1",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": account_id,
                        "create": {
                            self._SUBMISSION_CREATE_KEY: {
                                "emailId": f"#{self._EMAIL_CREATE_KEY}",
                                "identityId": identity_id,
                                "envelope": envelope,
                            }
                        },
                        "onSuccessUpdateEmail": {
                            f"#{self._SUBMISSION_CREATE_KEY}": {
                                f"mailboxIds/{draft_id}": None,
                                f"mailboxIds/{sent_id}": True,
                                "keywords/$draft": None,
                            }
                        },
                    },
                    "c2",
                ],
            ],
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:ietf:params:jmap:mail",
                "urn:ietf:params:jmap:submission",
            ],
        }
        response_body = await self._call_jmap(body)

        email_args = self._unwrap_tagged_response(response_body, "c1", "Email/set")
        not_created = email_args.get("notCreated") or {}
        if self._EMAIL_CREATE_KEY in not_created:
            error = not_created[self._EMAIL_CREATE_KEY]
            raise MailClientError(
                f"Mail server refused to create outgoing email: "
                f"{error.get('type')} ({error.get('description', 'no description')})"
            )
        created_email = (email_args.get("created") or {}).get(self._EMAIL_CREATE_KEY)
        if created_email is None:
            raise MailClientError("Mail server did not return created Email id")

        submission_args = self._unwrap_tagged_response(response_body, "c2", "EmailSubmission/set")
        not_submitted = submission_args.get("notCreated") or {}
        if self._SUBMISSION_CREATE_KEY in not_submitted:
            error = not_submitted[self._SUBMISSION_CREATE_KEY]
            raise MailClientError(
                f"Mail server refused to submit outgoing email: "
                f"{error.get('type')} ({error.get('description', 'no description')})"
            )
        created_submission = (submission_args.get("created") or {}).get(self._SUBMISSION_CREATE_KEY)
        if created_submission is None:
            raise MailClientError("Mail server did not return created EmailSubmission id")

        update_args = self._unwrap_tagged_response(response_body, "c2", "Email/set")
        updated = update_args.get("updated") or {}
        if str(created_email["id"]) not in updated:
            not_updated = update_args.get("notUpdated") or {}
            error = not_updated.get(str(created_email["id"]), {})
            raise MailClientError(
                f"Mail server submitted email but did not move it to Sent: "
                f"{error.get('type', 'missingUpdate')} "
                f"({error.get('description', 'no description')})"
            )

        return MailSendResult(
            email_id=str(created_email["id"]),
            submission_id=str(created_submission["id"]),
        )

    async def save_sent_message(
        self,
        *,
        account_id: str,
        from_address: str,
        to: Sequence[str],
        subject: str,
        text: str,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
    ) -> str:
        sent_id = (await self._resolve_mailbox_ids_by_role(account_id, ("sent",)))["sent"]

        def addresses(values: Sequence[str]) -> list[dict[str, str]]:
            return [{"email": value} for value in values]

        email: dict = {
            "mailboxIds": {sent_id: True},
            "from": [{"email": from_address}],
            "to": addresses(to),
            "subject": subject,
            "bodyValues": {"body": {"value": text, "charset": "utf-8"}},
            "textBody": [{"partId": "body", "type": "text/plain"}],
        }
        if cc:
            email["cc"] = addresses(cc)
        if bcc:
            email["bcc"] = addresses(bcc)
        body = {
            "methodCalls": [
                [
                    "Email/set",
                    {"accountId": account_id, "create": {self._EMAIL_CREATE_KEY: email}},
                    "c1",
                ]
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        arguments = self._unwrap_response(await self._call_jmap(body), "Email/set")
        error = (arguments.get("notCreated") or {}).get(self._EMAIL_CREATE_KEY)
        if error:
            raise MailClientError(
                "Mail server refused to save sent email: "
                f"{error.get('type')} ({error.get('description', 'no description')})"
            )
        created = (arguments.get("created") or {}).get(self._EMAIL_CREATE_KEY)
        if created is None or not created.get("id"):
            raise MailClientError("Mail server did not return saved Email id")
        return str(created["id"])

    async def list_mailboxes(self, *, account_id: str) -> Sequence[MailboxInfo]:
        body = {
            "methodCalls": [["Mailbox/get", {"accountId": account_id, "ids": None}, "c1"]],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        arguments = self._unwrap_response(await self._call_jmap(body), "Mailbox/get")
        mailboxes: list[MailboxInfo] = []
        for mailbox in arguments.get("list") or []:
            mailboxes.append(
                MailboxInfo(
                    id=str(mailbox["id"]),
                    name=str(mailbox.get("name") or ""),
                    role=None if mailbox.get("role") in (None, "") else str(mailbox["role"]),
                    total_emails=int(mailbox.get("totalEmails") or 0),
                    total_threads=int(mailbox.get("totalThreads") or 0),
                    unread_emails=int(mailbox.get("unreadEmails") or 0),
                    unread_threads=int(mailbox.get("unreadThreads") or 0),
                )
            )
        return tuple(mailboxes)

    async def list_messages(
        self,
        *,
        account_id: str,
        mailbox_role: str,
        limit: int = 50,
        collapse_threads: bool = True,
    ) -> Sequence[MailMessageSummary]:
        mailbox_ids = await self._resolve_mailbox_ids_by_role(account_id, (mailbox_role,))
        mailbox_id = mailbox_ids[mailbox_role]
        body = {
            "methodCalls": [
                [
                    "Email/query",
                    {
                        "accountId": account_id,
                        "filter": {"inMailbox": mailbox_id},
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "collapseThreads": collapse_threads,
                        "position": 0,
                        "limit": limit,
                    },
                    "c1",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {"resultOf": "c1", "name": "Email/query", "path": "/ids"},
                        "properties": [
                            "threadId",
                            "mailboxIds",
                            "keywords",
                            "hasAttachment",
                            "from",
                            "subject",
                            "receivedAt",
                            "size",
                            "preview",
                        ],
                    },
                    "c2",
                ],
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        response_body = await self._call_jmap(body)
        arguments = self._unwrap_tagged_response(response_body, "c2", "Email/get")
        return tuple(self._message_summary(email) for email in (arguments.get("list") or []))

    async def get_message(self, *, account_id: str, message_id: str) -> MailMessageDetail:
        body = {
            "methodCalls": [
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "ids": [message_id],
                        "properties": [
                            "threadId",
                            "mailboxIds",
                            "keywords",
                            "hasAttachment",
                            "from",
                            "to",
                            "cc",
                            "bcc",
                            "replyTo",
                            "subject",
                            "receivedAt",
                            "size",
                            "preview",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                        ],
                        "bodyProperties": ["partId", "type"],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "c1",
                ]
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        arguments = self._unwrap_response(await self._call_jmap(body), "Email/get")
        emails = arguments.get("list") or []
        if not emails:
            raise MailClientError(f"Mail server returned no message for id {message_id!r}")
        return self._message_detail(emails[0])

    async def update_message(
        self, *, account_id: str, message_id: str, patch: MailMessageUpdate
    ) -> MailMessageDetail:
        mailbox_patch: dict[str, bool | None] = {}
        if patch.mailbox_role is not None:
            all_mailboxes = await self.list_mailboxes(account_id=account_id)
            role_to_id = {mailbox.role: mailbox.id for mailbox in all_mailboxes if mailbox.role}
            target_mailbox_id = role_to_id.get(patch.mailbox_role)
            if target_mailbox_id is None:
                raise MailClientError(
                    f"Mail server account {account_id!r} is missing mailbox role {patch.mailbox_role!r}"
                )
            current = await self.get_message(account_id=account_id, message_id=message_id)
            system_roles = {"inbox", "archive", "trash", "junk", "sent", "drafts"}
            mailbox_ids = set(current.mailbox_ids)
            for role, mailbox_id in role_to_id.items():
                if (
                    role in system_roles
                    and mailbox_id in mailbox_ids
                    and mailbox_id != target_mailbox_id
                ):
                    mailbox_patch[f"mailboxIds/{mailbox_id}"] = None
            mailbox_patch[f"mailboxIds/{target_mailbox_id}"] = True

        keyword_patch: dict[str, bool | None] = {}
        if patch.seen is not None:
            keyword_patch["keywords/$seen"] = True if patch.seen else None
        if patch.flagged is not None:
            keyword_patch["keywords/$flagged"] = True if patch.flagged else None

        update_fields = {**mailbox_patch, **keyword_patch}
        if not update_fields:
            return await self.get_message(account_id=account_id, message_id=message_id)

        body = {
            "methodCalls": [
                [
                    "Email/set",
                    {"accountId": account_id, "update": {message_id: update_fields}},
                    "c1",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "ids": [message_id],
                        "properties": [
                            "threadId",
                            "mailboxIds",
                            "keywords",
                            "hasAttachment",
                            "from",
                            "to",
                            "cc",
                            "bcc",
                            "replyTo",
                            "subject",
                            "receivedAt",
                            "size",
                            "preview",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                        ],
                        "bodyProperties": ["partId", "type"],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "c2",
                ],
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        response_body = await self._call_jmap(body)
        arguments = self._unwrap_tagged_response(response_body, "c1", "Email/set")
        not_updated = arguments.get("notUpdated") or {}
        if message_id in not_updated:
            error = not_updated[message_id]
            raise MailClientError(
                f"Mail server refused to update message {message_id!r}: "
                f"{error.get('type')} ({error.get('description', 'no description')})"
            )
        get_args = self._unwrap_tagged_response(response_body, "c2", "Email/get")
        emails = get_args.get("list") or []
        if not emails:
            raise MailClientError(f"Mail server returned no updated message for id {message_id!r}")
        return self._message_detail(emails[0])

    async def mark_mailbox_read(self, *, account_id: str, mailbox_role: str) -> int:
        mailbox_ids = await self._resolve_mailbox_ids_by_role(account_id, (mailbox_role,))
        mailbox_id = mailbox_ids[mailbox_role]
        query_body = {
            "methodCalls": [
                [
                    "Email/query",
                    {
                        "accountId": account_id,
                        "filter": {"inMailbox": mailbox_id, "notKeyword": "$seen"},
                        # A mailbox can hold more unread mail than one page; the
                        # cap keeps a single JMAP call bounded while covering any
                        # realistic inbox. Stalwart returns at most this many ids.
                        "limit": 1000,
                    },
                    "c1",
                ]
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        query_args = self._unwrap_response(await self._call_jmap(query_body), "Email/query")
        message_ids = [str(message_id) for message_id in (query_args.get("ids") or [])]
        if not message_ids:
            return 0

        set_body = {
            "methodCalls": [
                [
                    "Email/set",
                    {
                        "accountId": account_id,
                        "update": {
                            message_id: {"keywords/$seen": True} for message_id in message_ids
                        },
                    },
                    "c1",
                ]
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        set_args = self._unwrap_response(await self._call_jmap(set_body), "Email/set")
        updated = set_args.get("updated") or {}
        return len(updated)

    async def list_thread_messages(
        self, *, account_id: str, thread_id: str
    ) -> Sequence[MailMessageDetail]:
        body = {
            "methodCalls": [
                ["Thread/get", {"accountId": account_id, "ids": [thread_id]}, "c1"],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {
                            "resultOf": "c1",
                            "name": "Thread/get",
                            "path": "/list/0/emailIds",
                        },
                        "properties": [
                            "threadId",
                            "mailboxIds",
                            "keywords",
                            "hasAttachment",
                            "from",
                            "to",
                            "cc",
                            "bcc",
                            "replyTo",
                            "subject",
                            "receivedAt",
                            "size",
                            "preview",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                        ],
                        "bodyProperties": ["partId", "type"],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "c2",
                ],
            ],
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        }
        response_body = await self._call_jmap(body)
        thread_args = self._unwrap_tagged_response(response_body, "c1", "Thread/get")
        threads = thread_args.get("list") or []
        if not threads:
            raise MailClientError(f"Mail server returned no thread for id {thread_id!r}")
        email_args = self._unwrap_tagged_response(response_body, "c2", "Email/get")
        details = [self._message_detail(email) for email in (email_args.get("list") or [])]
        details.sort(key=lambda item: item.received_at)
        return tuple(details)
