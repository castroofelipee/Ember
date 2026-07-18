import json

import httpx
import pytest

from ember.config import env
from ember.mail import (
    MailAuthenticationError,
    MailClientError,
    MailConnectionError,
    MailTimeoutError,
    ResendMailSender,
    StalwartMailClient,
    StalwartMailSender,
    get_mail_sender,
)


def _sender_with(handler, *, mailbox_client=None) -> ResendMailSender:
    return ResendMailSender(
        "re_secret",
        mailbox_client=mailbox_client,
        transport=httpx.MockTransport(handler),
    )


async def test_resend_sends_expected_payload_and_authorization() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "resend-123"})

    result = await _sender_with(handler).send_message(
        account_id="stalwart-account",
        from_address="ada@example.com",
        to=("grace@example.com",),
        cc=("team@example.com",),
        bcc=("audit@example.com",),
        subject="Hello",
        text="From Ember",
    )

    assert seen == {
        "url": "https://api.resend.com/emails",
        "authorization": "Bearer re_secret",
        "payload": {
            "from": "ada@example.com",
            "to": ["grace@example.com"],
            "cc": ["team@example.com"],
            "bcc": ["audit@example.com"],
            "subject": "Hello",
            "text": "From Ember",
        },
    }
    assert result.email_id == "resend-123"
    assert result.submission_id == "resend-123"


@pytest.mark.parametrize("status", [401, 403])
async def test_resend_auth_errors_are_normalized(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    with pytest.raises(MailAuthenticationError):
        await _sender_with(handler).send_message(
            account_id="a",
            from_address="a@example.com",
            to=("b@example.com",),
            subject="Hi",
            text="Body",
        )


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_resend_provider_errors_are_normalized(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="rejected")

    with pytest.raises(MailClientError):
        await _sender_with(handler).send_message(
            account_id="a",
            from_address="a@example.com",
            to=("b@example.com",),
            subject="Hi",
            text="Body",
        )


async def test_resend_timeout_and_connection_errors_are_normalized() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(MailTimeoutError):
        await _sender_with(timeout).send_message(
            account_id="a",
            from_address="a@example.com",
            to=("b@example.com",),
            subject="Hi",
            text="Body",
        )

    def connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(MailConnectionError):
        await _sender_with(connection).send_message(
            account_id="a",
            from_address="a@example.com",
            to=("b@example.com",),
            subject="Hi",
            text="Body",
        )
