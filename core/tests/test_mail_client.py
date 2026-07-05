"""Tests for the mail infrastructure (docs/rfc/mail-module.md).

Covers the client abstraction, the Stalwart client's construction/config
contract, the factory, and `health_check` against a mocked HTTP transport — no
real Stalwart server, DB, or network is involved.
"""

import json

import httpx
import pytest

from ember.config import env
from ember.mail import (
    MailAccountAlreadyExistsError,
    MailAuthenticationError,
    MailClient,
    MailClientError,
    MailConnectionError,
    MailDomainNotProvisionedError,
    MailTimeoutError,
    StalwartMailClient,
    get_mail_client,
)
from ember.mail.client import MailAccount


def _client_with(handler) -> StalwartMailClient:
    """A StalwartMailClient whose HTTP calls are served by `handler` instead of
    the network, via httpx's MockTransport."""
    return StalwartMailClient(
        base_url="https://mail.example.com",
        admin_token="secret-token",
        transport=httpx.MockTransport(handler),
    )


def test_mail_client_is_abstract() -> None:
    with pytest.raises(TypeError):
        MailClient()  # type: ignore[abstract]


def test_stalwart_requires_base_url() -> None:
    with pytest.raises(ValueError):
        StalwartMailClient(base_url="", admin_token="token")


def test_stalwart_normalizes_base_url() -> None:
    client = StalwartMailClient(base_url="https://mail.example.com/", admin_token="token")
    assert client.base_url == "https://mail.example.com"


async def test_stalwart_password_rotation_not_implemented_yet() -> None:
    client = StalwartMailClient(base_url="https://mail.example.com", admin_token="token")

    with pytest.raises(NotImplementedError):
        await client.set_password("account-id", "pw")


def test_get_mail_client_returns_none_when_disabled() -> None:
    # MAIL_ENABLED defaults to False, so mail is off unless explicitly configured.
    assert env["MAIL_ENABLED"] is False
    assert get_mail_client() is None


def test_get_mail_client_builds_stalwart_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(env, "MAIL_ENABLED", True)
    monkeypatch.setitem(env, "MAIL_SERVER_URL", "https://mail.example.com")
    monkeypatch.setitem(env, "MAIL_ADMIN_TOKEN", "token")

    client = get_mail_client()

    assert isinstance(client, StalwartMailClient)
    assert client.base_url == "https://mail.example.com"


def test_mail_account_is_a_value() -> None:
    account = MailAccount(id="abc", address="ada@example.com")
    assert account.id == "abc"
    assert account.address == "ada@example.com"


async def test_health_check_success_sends_bearer_and_returns_true() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return _jmap_response([["Core/echo", {"ember": "health_check"}, "c1"]])

    client = _client_with(handler)

    assert await client.health_check() is True
    # v0.16 management surface: POST the JMAP envelope to /jmap, not the old
    # REST /api/principal (which no longer exists).
    assert seen["path"] == "/jmap"
    assert seen["method"] == "POST"
    assert seen["authorization"] == "Bearer secret-token"
    [[method_name, _args, _tag]] = seen["body"]["methodCalls"]
    assert method_name == "Core/echo"
    assert seen["body"]["using"] == ["urn:ietf:params:jmap:core"]


async def test_health_check_401_raises_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"type": "about:blank", "status": 401})

    with pytest.raises(MailAuthenticationError):
        await _client_with(handler).health_check()


async def test_health_check_403_raises_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(MailAuthenticationError):
        await _client_with(handler).health_check()


async def test_health_check_unexpected_status_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(MailClientError) as exc_info:
        await _client_with(handler).health_check()
    # A generic client error, not one of the more specific subclasses.
    assert not isinstance(exc_info.value, (MailAuthenticationError, MailConnectionError))


async def test_health_check_connection_error_raises_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(MailConnectionError):
        await _client_with(handler).health_check()


async def test_health_check_timeout_raises_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(MailTimeoutError):
        await _client_with(handler).health_check()


def _jmap_response(method_responses: list) -> httpx.Response:
    return httpx.Response(200, json={"methodResponses": method_responses})


def _created_response(account_id: int = 42, email: str = "ada@example.com") -> httpx.Response:
    return _jmap_response(
        [
            [
                "x:Account/set",
                {"created": {"new1": {"id": account_id, "emailAddress": email}}},
                "c1",
            ]
        ]
    )


def _domain_query_response(ids: tuple[str, ...] = ("dom1",)) -> httpx.Response:
    return _jmap_response([["x:Domain/query", {"ids": list(ids)}, "c1"]])


def _client_for_create(on_account_set, *, domain_ids: tuple[str, ...] = ("dom1",)):
    """A client whose transport answers `x:Domain/query` (the domain-id lookup
    create_account does first) with `domain_ids`, and routes the `x:Account/set`
    call to `on_account_set(request) -> Response`."""

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["methodCalls"][0][0]
        if method == "x:Domain/query":
            return _domain_query_response(domain_ids)
        return on_account_set(request)

    return _client_with(handler)


async def test_create_account_success_returns_dto_and_sends_bearer() -> None:
    seen: dict = {}

    def on_set(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["content_type"] = request.headers.get("Content-Type")
        seen["body"] = json.loads(request.content)
        return _created_response(account_id=42, email="ada@example.com")

    account = await _client_for_create(on_set).create_account("ada@example.com", "hunter2")

    assert account.id == "42"
    assert account.address == "ada@example.com"
    assert seen["path"] == "/jmap"
    assert seen["authorization"] == "Bearer secret-token"
    assert seen["content_type"] == "application/json"

    body = seen["body"]
    assert body["using"] == ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
    [[method_name, method_args, tag]] = body["methodCalls"]
    assert method_name == "x:Account/set"
    assert tag == "c1"
    fields = method_args["create"]["new1"]
    assert fields["@type"] == "User"
    assert fields["name"] == "ada"
    # The resolved Domain Id, not the bare domain name.
    assert fields["domainId"] == "dom1"
    assert fields["credentials"] == {"0": {"@type": "Password", "secret": "hunter2"}}
    assert fields["roles"] == {"@type": "User"}
    assert fields["permissions"] == {"@type": "Inherit"}
    assert fields["encryptionAtRest"] == {"@type": "Disabled"}
    assert fields["quotas"] == {}
    assert fields["aliases"] == {}
    assert fields["memberGroupIds"] == {}


async def test_create_account_resolves_domain_id_first() -> None:
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["methodCalls"][0])
        method = body["methodCalls"][0][0]
        if method == "x:Domain/query":
            return _domain_query_response(("dom-xyz",))
        return _created_response()

    await _client_with(handler).create_account("ada@example.com", "pw")

    # First call resolves the domain by name; second creates with that id.
    assert calls[0][0] == "x:Domain/query"
    assert calls[0][1] == {"filter": {"name": "example.com"}}
    assert calls[1][0] == "x:Account/set"
    assert calls[1][1]["create"]["new1"]["domainId"] == "dom-xyz"


async def test_create_account_domain_not_on_server_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Empty id list: no Domain object matches the address's domain.
        return _domain_query_response(())

    with pytest.raises(MailDomainNotProvisionedError):
        await _client_with(handler).create_account("ada@example.com", "pw")


async def test_create_account_sends_quota_when_given() -> None:
    seen: dict = {}

    def on_set(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _created_response()

    await _client_for_create(on_set).create_account("ada@example.com", "pw", quota_bytes=1024)

    fields = seen["body"]["methodCalls"][0][1]["create"]["new1"]
    assert fields["quotas"] == {"maxDiskQuota": 1024}


async def test_create_account_rejects_address_without_domain() -> None:
    client = StalwartMailClient(base_url="https://mail.example.com", admin_token="token")
    with pytest.raises(ValueError):
        await client.create_account("not-an-email", "pw")


async def test_create_account_already_exists_raises_specific_error() -> None:
    def on_set(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [
                [
                    "x:Account/set",
                    {
                        "notCreated": {
                            "new1": {
                                "type": "alreadyExists",
                                "description": "an account with this name already exists",
                            }
                        }
                    },
                    "c1",
                ]
            ]
        )

    with pytest.raises(MailAccountAlreadyExistsError):
        await _client_for_create(on_set).create_account("ada@example.com", "pw")


async def test_create_account_other_not_created_raises_generic_client_error() -> None:
    def on_set(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [
                [
                    "x:Account/set",
                    {
                        "notCreated": {
                            "new1": {
                                "type": "invalidProperties",
                                "description": "domainId is not a valid domain",
                            }
                        }
                    },
                    "c1",
                ]
            ]
        )

    with pytest.raises(MailClientError) as exc_info:
        await _client_for_create(on_set).create_account("ada@example.com", "pw")
    assert not isinstance(exc_info.value, MailAccountAlreadyExistsError)
    assert "invalidProperties" in str(exc_info.value)


async def test_create_account_top_level_jmap_error_raises_client_error() -> None:
    def on_set(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [["error", {"type": "unknownMethod", "description": "no such method"}, "c1"]]
        )

    with pytest.raises(MailClientError):
        await _client_for_create(on_set).create_account("ada@example.com", "pw")


async def test_create_account_empty_method_responses_raises_client_error() -> None:
    def on_set(request: httpx.Request) -> httpx.Response:
        return _jmap_response([])

    with pytest.raises(MailClientError):
        await _client_for_create(on_set).create_account("ada@example.com", "pw")


async def test_create_account_401_raises_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(MailAuthenticationError):
        await _client_with(handler).create_account("ada@example.com", "pw")


async def test_create_account_unexpected_status_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(MailClientError) as exc_info:
        await _client_with(handler).create_account("ada@example.com", "pw")
    assert not isinstance(exc_info.value, (MailAuthenticationError, MailConnectionError))


async def test_create_account_connection_error_raises_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(MailConnectionError):
        await _client_with(handler).create_account("ada@example.com", "pw")


async def test_create_account_timeout_raises_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(MailTimeoutError):
        await _client_with(handler).create_account("ada@example.com", "pw")


async def test_delete_account_success_sends_destroy() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _jmap_response([["x:Account/set", {"destroyed": ["42"]}, "c1"]])

    await _client_with(handler).delete_account("42")

    assert seen["path"] == "/jmap"
    [[method_name, method_args, _tag]] = seen["body"]["methodCalls"]
    assert method_name == "x:Account/set"
    assert method_args == {"destroy": ["42"]}


async def test_delete_account_not_destroyed_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [
                [
                    "x:Account/set",
                    {
                        "notDestroyed": {
                            "42": {"type": "notFound", "description": "no such account"}
                        }
                    },
                    "c1",
                ]
            ]
        )

    with pytest.raises(MailClientError) as exc_info:
        await _client_with(handler).delete_account("42")
    assert "notFound" in str(exc_info.value)


async def test_delete_account_top_level_jmap_error_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [["error", {"type": "unknownMethod", "description": "no such method"}, "c1"]]
        )

    with pytest.raises(MailClientError):
        await _client_with(handler).delete_account("42")


async def test_delete_account_empty_method_responses_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _jmap_response([])

    with pytest.raises(MailClientError):
        await _client_with(handler).delete_account("42")


async def test_delete_account_missing_destroyed_and_not_destroyed_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _jmap_response([["x:Account/set", {}, "c1"]])

    with pytest.raises(MailClientError):
        await _client_with(handler).delete_account("42")


async def test_delete_account_401_raises_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(MailAuthenticationError):
        await _client_with(handler).delete_account("42")


async def test_delete_account_connection_error_raises_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(MailConnectionError):
        await _client_with(handler).delete_account("42")


async def test_delete_account_timeout_raises_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(MailTimeoutError):
        await _client_with(handler).delete_account("42")


async def test_send_message_creates_email_and_submission() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        method = body["methodCalls"][0][0]
        if method == "Mailbox/get":
            return _jmap_response(
                [
                    [
                        "Mailbox/get",
                        {
                            "list": [
                                {"id": "drafts-id", "role": "drafts"},
                                {"id": "sent-id", "role": "sent"},
                            ]
                        },
                        "c1",
                    ]
                ]
            )
        if method == "Identity/get":
            return _jmap_response(
                [
                    [
                        "Identity/get",
                        {"list": [{"id": "identity-id", "email": "ada@example.com"}]},
                        "c1",
                    ]
                ]
            )
        return _jmap_response(
            [
                ["Email/set", {"created": {"email1": {"id": "email-id"}}}, "c1"],
                [
                    "EmailSubmission/set",
                    {"created": {"submission1": {"id": "submission-id"}}},
                    "c2",
                ],
                ["Email/set", {"updated": {"email-id": None}}, "c2"],
            ]
        )

    result = await _client_with(handler).send_message(
        account_id="account-id",
        from_address="ada@example.com",
        to=["grace@example.com"],
        cc=["team@example.com"],
        subject="Status",
        text="Hello",
    )

    assert result.email_id == "email-id"
    assert result.submission_id == "submission-id"
    assert calls[0]["methodCalls"][0] == [
        "Mailbox/get",
        {"accountId": "account-id", "ids": None},
        "c1",
    ]
    assert calls[1]["methodCalls"][0] == [
        "Identity/get",
        {"accountId": "account-id", "ids": None},
        "c1",
    ]

    [[email_method, email_args, email_tag], [submission_method, submission_args, submission_tag]] = (
        calls[2]["methodCalls"]
    )
    assert email_method == "Email/set"
    assert email_tag == "c1"
    created_email = email_args["create"]["email1"]
    assert created_email["mailboxIds"] == {"drafts-id": True}
    assert created_email["keywords"] == {"$draft": True}
    assert created_email["from"] == [{"email": "ada@example.com"}]
    assert created_email["to"] == [{"email": "grace@example.com"}]
    assert created_email["cc"] == [{"email": "team@example.com"}]
    assert created_email["subject"] == "Status"
    assert created_email["bodyValues"] == {"body": {"value": "Hello", "charset": "utf-8"}}
    assert created_email["textBody"] == [{"partId": "body", "type": "text/plain"}]

    assert submission_method == "EmailSubmission/set"
    assert submission_tag == "c2"
    assert submission_args["create"] == {
        "submission1": {
            "emailId": "#email1",
            "identityId": "identity-id",
            "envelope": {
                "mailFrom": {"email": "ada@example.com", "parameters": None},
                "rcptTo": [
                    {"email": "grace@example.com", "parameters": None},
                    {"email": "team@example.com", "parameters": None},
                ],
            },
        }
    }
    assert submission_args["onSuccessUpdateEmail"] == {
        "#submission1": {
            "mailboxIds/drafts-id": None,
            "mailboxIds/sent-id": True,
            "keywords/$draft": None,
        }
    }


async def test_send_message_missing_mailbox_role_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _jmap_response(
            [["Mailbox/get", {"list": [{"id": "drafts-id", "role": "drafts"}]}, "c1"]]
        )

    with pytest.raises(MailClientError) as exc_info:
        await _client_with(handler).send_message(
            account_id="account-id",
            from_address="ada@example.com",
            to=["grace@example.com"],
            subject="Status",
            text="Hello",
        )
    assert "sent" in str(exc_info.value)


async def test_send_message_without_sent_update_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body["methodCalls"][0][0]
        if method == "Mailbox/get":
            return _jmap_response(
                [
                    [
                        "Mailbox/get",
                        {
                            "list": [
                                {"id": "drafts-id", "role": "drafts"},
                                {"id": "sent-id", "role": "sent"},
                            ]
                        },
                        "c1",
                    ]
                ]
            )
        if method == "Identity/get":
            return _jmap_response(
                [["Identity/get", {"list": [{"id": "identity-id"}]}, "c1"]]
            )
        return _jmap_response(
            [
                ["Email/set", {"created": {"email1": {"id": "email-id"}}}, "c1"],
                [
                    "EmailSubmission/set",
                    {"created": {"submission1": {"id": "submission-id"}}},
                    "c2",
                ],
            ]
        )

    with pytest.raises(MailClientError) as exc_info:
        await _client_with(handler).send_message(
            account_id="account-id",
            from_address="ada@example.com",
            to=["grace@example.com"],
            subject="Status",
            text="Hello",
        )
    assert "Email/set" in str(exc_info.value)
