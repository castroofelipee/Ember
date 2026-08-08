"""GitHub integration — base infrastructure.

Public surface for the GitHub provider abstraction: the client seam, the OAuth
handshake, and how to obtain a configured client. Endpoints and persistence
live in `ember.routers.github` / `ember.services.github`.
"""

from ember.config import github_configured
from ember.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubConnectionError,
    GitHubError,
    GitHubIssue,
    GitHubLabel,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRepo,
    GitHubTimeoutError,
    GitHubUser,
    GitHubValidationError,
    IssueState,
    RestGitHubClient,
)
from ember.github.oauth import (
    OAUTH_SCOPES,
    GitHubOAuthError,
    OAuthToken,
    authorize_url,
    exchange_code,
    refresh_access_token,
)

__all__ = [
    "GitHubAuthError",
    "GitHubClient",
    "GitHubConnectionError",
    "GitHubError",
    "GitHubIssue",
    "GitHubLabel",
    "GitHubNotFoundError",
    "GitHubOAuthError",
    "GitHubRateLimitError",
    "GitHubRepo",
    "GitHubTimeoutError",
    "GitHubUser",
    "GitHubValidationError",
    "IssueState",
    "OAUTH_SCOPES",
    "OAuthToken",
    "RestGitHubClient",
    "authorize_url",
    "exchange_code",
    "get_github_client",
    "refresh_access_token",
]


def get_github_client(access_token: str) -> GitHubClient | None:
    """Build a client for one user's token, or None when the integration is not
    configured.

    Returning None (rather than raising) keeps GitHub strictly optional: Ember
    runs identically with no OAuth App set up, which is the default. This is
    also the single place that decides which concrete backend is in use — tests
    override it to inject a fake.
    """
    if not github_configured():
        return None
    return RestGitHubClient(access_token)
