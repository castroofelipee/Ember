"""Tests for the mail infrastructure (docs/rfc/mail-module.md).

Covers the client abstraction, the Stalwart client's construction/config
contract, the factory, and `health_check` against a mocked HTTP transport — no
real Stalwart server, DB, or network is involved.
"""

import httpx
import pytest

from ember.config import env
from ember.mail import (
    MailAuthenticationError,
    MailClient,
    MailClientError,
    MailConnectionError,
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


async def test_stalwart_provisioning_not_implemented_yet() -> None:
    client = StalwartMailClient(base_url="https://mail.example.com", admin_token="token")

    with pytest.raises(NotImplementedError):
        await client.create_account("ada@example.com", "pw")
    with pytest.raises(NotImplementedError):
        await client.set_password("account-id", "pw")
    with pytest.raises(NotImplementedError):
        await client.delete_account("account-id")


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
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["accept"] = request.headers.get("Accept")
        return httpx.Response(200, json={"items": [], "total": 0})

    client = _client_with(handler)

    assert await client.health_check() is True
    assert seen["path"] == "/api/principal"
    assert seen["authorization"] == "Bearer secret-token"
    assert seen["accept"] == "application/json"


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
