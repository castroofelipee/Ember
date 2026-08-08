import asyncio
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from ember.config import env

IssueState = Literal["open", "closed", "all"]


_PULL_REQUEST_KEY = "pull_request"

_API_VERSION = "2022-11-28"
_MAX_PER_PAGE = 100


class GitHubError(Exception):
    """Base error for GitHub operations. Concrete clients raise this (or a
    subclass) so callers handle provider failures without depending on
    httpx's exception types."""


class GitHubConnectionError(GitHubError):
    """GitHub could not be reached (DNS, refused connection, transport failure)."""


class GitHubTimeoutError(GitHubError):
    """GitHub did not respond within the configured timeout."""


class GitHubAuthError(GitHubError):
    """The token was rejected or lacks the scope the operation needs. Usually
    means the user revoked the grant on GitHub's side and must reconnect."""


class GitHubNotFoundError(GitHubError):
    """The repository or issue does not exist, or the token cannot see it.
    GitHub returns 404 rather than 403 for private resources it won't admit to."""


class GitHubRateLimitError(GitHubError):
    """The token's rate limit is exhausted."""

    def __init__(self, message: str, *, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class GitHubValidationError(GitHubError):
    """GitHub rejected the request body (422) — e.g. an assignee who is not a
    collaborator, or a label that does not exist on the repository."""


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    avatar_url: str | None
    name: str | None = None


@dataclass(frozen=True)
class GitHubRepo:
    id: int
    owner: str
    name: str
    full_name: str
    private: bool
    html_url: str
    description: str | None
    is_organization: bool
    open_issues_count: int = 0


@dataclass(frozen=True)
class GitHubLabel:
    name: str
    color: str
    description: str | None = None


@dataclass(frozen=True)
class GitHubIssue:
    id: int
    number: int
    title: str
    body: str | None
    state: str
    state_reason: str | None
    html_url: str
    assignees: tuple[GitHubUser, ...]
    labels: tuple[GitHubLabel, ...]
    comments: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    author: GitHubUser | None
    milestone: str | None
    repo_full_name: str = ""
    repo_id: int = 0


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_datetime(value: str | None) -> datetime:
    parsed = _parse_datetime(value)
    return parsed if parsed is not None else datetime.now(UTC)


def _parse_user(payload: dict[str, Any] | None) -> GitHubUser | None:
    if not payload:
        return None
    return GitHubUser(
        id=int(payload.get("id") or 0),
        login=str(payload.get("login") or ""),
        avatar_url=payload.get("avatar_url"),
        name=payload.get("name"),
    )


def _parse_repo(payload: dict[str, Any]) -> GitHubRepo:
    owner = payload.get("owner") or {}
    return GitHubRepo(
        id=int(payload["id"]),
        owner=str(owner.get("login") or ""),
        name=str(payload.get("name") or ""),
        full_name=str(payload.get("full_name") or ""),
        private=bool(payload.get("private")),
        html_url=str(payload.get("html_url") or ""),
        description=payload.get("description"),
        is_organization=str(owner.get("type") or "") == "Organization",
        open_issues_count=int(payload.get("open_issues_count") or 0),
    )


def _parse_label(payload: dict[str, Any] | str) -> GitHubLabel:
    if isinstance(payload, str):
        return GitHubLabel(name=payload, color="ededed")
    return GitHubLabel(
        name=str(payload.get("name") or ""),
        color=str(payload.get("color") or "ededed"),
        description=payload.get("description"),
    )


def _parse_issue(payload: dict[str, Any]) -> GitHubIssue:
    milestone = payload.get("milestone") or {}
    return GitHubIssue(
        id=int(payload["id"]),
        number=int(payload["number"]),
        title=str(payload.get("title") or ""),
        body=payload.get("body"),
        state=str(payload.get("state") or "open"),
        state_reason=payload.get("state_reason"),
        html_url=str(payload.get("html_url") or ""),
        assignees=tuple(
            user
            for user in (_parse_user(item) for item in payload.get("assignees") or [])
            if user is not None
        ),
        labels=tuple(_parse_label(item) for item in payload.get("labels") or []),
        comments=int(payload.get("comments") or 0),
        created_at=_require_datetime(payload.get("created_at")),
        updated_at=_require_datetime(payload.get("updated_at")),
        closed_at=_parse_datetime(payload.get("closed_at")),
        author=_parse_user(payload.get("user")),
        milestone=milestone.get("title") if isinstance(milestone, dict) else None,
    )


class GitHubClient(ABC):
    """Everything Ember needs from GitHub, and nothing more."""

    @abstractmethod
    async def get_viewer(self) -> GitHubUser:
        """The account the token belongs to."""

    @abstractmethod
    async def list_accessible_repos(self, *, query: str | None = None) -> list[GitHubRepo]:
        """Repositories the token can reach — personal, organization, and those
        shared as a collaborator."""

    @abstractmethod
    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: IssueState = "open",
        assignee: str | None = None,
        labels: Sequence[str] | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> list[GitHubIssue]:
        """Issues on one repository, pull requests excluded."""

    @abstractmethod
    async def create_issue(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str | None = None,
        assignees: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
    ) -> GitHubIssue:
        """File a new issue."""

    @abstractmethod
    async def list_repo_labels(self, owner: str, repo: str) -> list[GitHubLabel]:
        """Labels defined on a repository, for the new-issue picker."""

    @abstractmethod
    async def list_repo_assignees(self, owner: str, repo: str) -> list[GitHubUser]:
        """Users who can be assigned issues on a repository."""


class RestGitHubClient(GitHubClient):
    """GitHub REST v3, authenticated as one user with their OAuth token."""

    def __init__(self, access_token: str, *, api_url: str | None = None) -> None:
        self._token = access_token
        self._api_url = (api_url or env["GITHUB_API_URL"]).rstrip("/")
        self._timeout = env["GITHUB_HTTP_TIMEOUT_SECONDS"]

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.request(
                    method,
                    f"{self._api_url}{path}",
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise GitHubTimeoutError(f"GitHub did not respond within {self._timeout}s.") from exc
        except httpx.HTTPError as exc:
            raise GitHubConnectionError(f"Could not reach GitHub: {exc}") from exc

        self._raise_for_status(response)
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return

        remaining = response.headers.get("x-ratelimit-remaining")
        if response.status_code in (403, 429) and remaining == "0":
            reset = response.headers.get("x-ratelimit-reset")
            reset_at = (
                datetime.fromtimestamp(int(reset), tz=UTC) if reset and reset.isdigit() else None
            )
            raise GitHubRateLimitError("GitHub rate limit exceeded.", reset_at=reset_at)

        if response.status_code == 401:
            raise GitHubAuthError("GitHub rejected the stored token. Reconnect the GitHub account.")
        if response.status_code == 403:
            raise GitHubAuthError("The GitHub token lacks permission for this resource.")
        if response.status_code == 404:
            raise GitHubNotFoundError("The GitHub resource does not exist or is not visible.")
        if response.status_code == 422:
            raise GitHubValidationError(_extract_message(response))
        raise GitHubError(f"GitHub returned {response.status_code}: {_extract_message(response)}")

    async def get_viewer(self) -> GitHubUser:
        payload = await self._request("GET", "/user")
        user = _parse_user(payload)
        if user is None:
            raise GitHubError("GitHub returned no account for this token.")
        return user

    async def list_accessible_repos(self, *, query: str | None = None) -> list[GitHubRepo]:
        pages = await asyncio.gather(
            *(
                self._request(
                    "GET",
                    "/user/repos",
                    params={
                        "affiliation": "owner,organization_member,collaborator",
                        "sort": "updated",
                        "per_page": _MAX_PER_PAGE,
                        "page": page,
                    },
                )
                for page in (1, 2, 3)
            )
        )
        repos = [_parse_repo(item) for page in pages for item in page or []]

        if query:
            needle = query.strip().lower()
            repos = [repo for repo in repos if needle in repo.full_name.lower()]
        return repos

    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: IssueState = "open",
        assignee: str | None = None,
        labels: Sequence[str] | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> list[GitHubIssue]:
        params: dict[str, Any] = {
            "state": state,
            "per_page": min(per_page, _MAX_PER_PAGE),
            "page": page,
            "sort": "updated",
            "direction": "desc",
        }
        if assignee:
            params["assignee"] = assignee
        if labels:
            params["labels"] = ",".join(labels)

        payload = await self._request("GET", f"/repos/{owner}/{repo}/issues", params=params)
        return [_parse_issue(item) for item in payload or [] if _PULL_REQUEST_KEY not in item]

    async def create_issue(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str | None = None,
        assignees: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
    ) -> GitHubIssue:
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if assignees:
            payload["assignees"] = list(assignees)
        if labels:
            payload["labels"] = list(labels)

        created = await self._request("POST", f"/repos/{owner}/{repo}/issues", json=payload)
        return _parse_issue(created)

    async def list_repo_labels(self, owner: str, repo: str) -> list[GitHubLabel]:
        payload = await self._request(
            "GET", f"/repos/{owner}/{repo}/labels", params={"per_page": _MAX_PER_PAGE}
        )
        return [_parse_label(item) for item in payload or []]

    async def list_repo_assignees(self, owner: str, repo: str) -> list[GitHubUser]:
        payload = await self._request(
            "GET", f"/repos/{owner}/{repo}/assignees", params={"per_page": _MAX_PER_PAGE}
        )
        return [user for user in (_parse_user(item) for item in payload or []) if user is not None]


def _extract_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        message = str(body.get("message") or "")
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            details = "; ".join(
                str(error.get("message") or error.get("field") or error)
                for error in errors
                if isinstance(error, (dict, str))
            )
            return f"{message}: {details}" if details else message
        return message or response.text[:200]
    return response.text[:200]
