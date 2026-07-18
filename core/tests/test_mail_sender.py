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
