from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from ember.config import env

OAUTH_SCOPES = "repo read:org"


class GitHubOAuthError(Exception):
    """The OAuth handshake failed — GitHub refused the code, the client
    credentials are wrong, or the response was unusable."""


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str


def _oauth_base() -> str:
    return env["GITHUB_OAUTH_BASE_URL"].rstrip("/")


def authorize_url(*, state: str, redirect_uri: str) -> str:
    query = urlencode(
        {
            "client_id": env["GITHUB_OAUTH_CLIENT_ID"],
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "state": state,
        }
    )
    return f"{_oauth_base()}/login/oauth/authorize?{query}"


async def _post_token(payload: dict[str, str]) -> OAuthToken:
    timeout = env["GITHUB_HTTP_TIMEOUT_SECONDS"]
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            response = await http.post(
                f"{_oauth_base()}/login/oauth/access_token",
                data=payload,
                headers={"Accept": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise GitHubOAuthError("GitHub did not respond during the token exchange.") from exc
    except httpx.HTTPError as exc:
        raise GitHubOAuthError(f"Could not reach GitHub for the token exchange: {exc}") from exc

    if not response.is_success:
        raise GitHubOAuthError(f"GitHub returned {response.status_code} for the token exchange.")

    try:
        body = response.json()
    except ValueError as exc:
        raise GitHubOAuthError("GitHub returned an unreadable token response.") from exc

    if body.get("error"):
        raise GitHubOAuthError(str(body.get("error_description") or body.get("error")))

    access_token = body.get("access_token")
    if not access_token:
        raise GitHubOAuthError("GitHub returned no access token.")

    expires_in = body.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in))
        if expires_in not in (None, "")
        else None
    )

    return OAuthToken(
        access_token=str(access_token),
        refresh_token=body.get("refresh_token") or None,
        expires_at=expires_at,
        scopes=str(body.get("scope") or ""),
    )


async def exchange_code(*, code: str, redirect_uri: str) -> OAuthToken:
    return await _post_token(
        {
            "client_id": env["GITHUB_OAUTH_CLIENT_ID"],
            "client_secret": env["GITHUB_OAUTH_CLIENT_SECRET"],
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )


async def refresh_access_token(*, refresh_token: str) -> OAuthToken:
    """Only reachable when the OAuth App has "expire user authorization tokens"
    enabled; classic tokens never expire and never land here."""
    return await _post_token(
        {
            "client_id": env["GITHUB_OAUTH_CLIENT_ID"],
            "client_secret": env["GITHUB_OAUTH_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
