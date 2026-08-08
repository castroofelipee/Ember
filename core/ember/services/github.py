import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.crypto import decrypt_secret, encrypt_secret
from ember.github import (
    GitHubClient,
    GitHubError,
    GitHubIssue,
    GitHubLabel,
    GitHubOAuthError,
    GitHubUser,
    IssueState,
    OAuthToken,
    get_github_client,
    refresh_access_token,
)
from ember.models import GitHubConnection, GitHubTrackedRepo

_REFRESH_MARGIN = timedelta(minutes=5)

_ISSUE_CACHE_TTL_SECONDS = 60
_issue_cache: dict[tuple, tuple[float, list[GitHubIssue]]] = {}


class GitHubNotConnectedError(Exception):
    """This user has not connected a GitHub account (or the integration is not
    configured at all)."""


class GitHubReauthRequiredError(Exception):
    """The stored grant is no longer usable — revoked on GitHub's side, or its
    refresh token expired. The user has to reconnect."""


class RepoNotTrackedError(Exception):
    """The repository is not on this workspace's tracked list, so it is not
    addressable from this workspace."""


class RepoAlreadyTrackedError(Exception):
    """The workspace already tracks this repository."""


@dataclass(frozen=True)
class RepoFailure:
    repo_id: int
    full_name: str
    message: str


@dataclass(frozen=True)
class IssueListing:
    issues: list[GitHubIssue]
    failures: list[RepoFailure]


LANE_OPEN = "open"
LANE_IN_PROGRESS = "in_progress"
LANE_DONE = "done"


def issue_lane(issue: GitHubIssue) -> str:
    """Map an issue onto one of the three board lanes.

    GitHub has no "in progress" state — an issue is open or closed. Assignment
    is the closest honest proxy for "someone has picked this up", so that is
    what the middle lane means, and the UI says so rather than implying GitHub
    tracks it.
    """
    if issue.state == "closed":
        return LANE_DONE
    return LANE_IN_PROGRESS if issue.assignees else LANE_OPEN


async def get_connection(db: AsyncSession, user_id: uuid.UUID) -> GitHubConnection | None:
    return (
        await db.execute(select(GitHubConnection).where(GitHubConnection.user_id == user_id))
    ).scalar_one_or_none()


async def upsert_connection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    token: OAuthToken,
    viewer: GitHubUser,
) -> GitHubConnection:
    """Store (or replace) a user's grant. Reconnecting overwrites in place so a
    user never accumulates stale tokens."""
    connection = await get_connection(db, user_id)
    if connection is None:
        connection = GitHubConnection(user_id=user_id, connected_at=datetime.now(UTC))
        db.add(connection)

    connection.github_user_id = viewer.id
    connection.github_login = viewer.login
    connection.avatar_url = viewer.avatar_url
    connection.scopes = token.scopes
    connection.access_token_encrypted = encrypt_secret(token.access_token)
    connection.refresh_token_encrypted = (
        encrypt_secret(token.refresh_token) if token.refresh_token else None
    )
    connection.access_token_expires_at = token.expires_at
    connection.connected_at = datetime.now(UTC)

    await db.flush()
    return connection


async def disconnect(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Drop the grant. The tracked-repo rows stay: they are workspace config,
    and another member's connection can still serve them."""
    connection = await get_connection(db, user_id)
    if connection is None:
        return False
    await db.delete(connection)
    await db.flush()
    return True


async def client_for_user(db: AsyncSession, user_id: uuid.UUID) -> GitHubClient:
    connection = await get_connection(db, user_id)
    if connection is None:
        raise GitHubNotConnectedError()

    access_token = decrypt_secret(connection.access_token_encrypted)

    expires_at = connection.access_token_expires_at
    if expires_at is not None and expires_at - _REFRESH_MARGIN <= datetime.now(UTC):
        if not connection.refresh_token_encrypted:
            raise GitHubReauthRequiredError()
        try:
            refreshed = await refresh_access_token(
                refresh_token=decrypt_secret(connection.refresh_token_encrypted)
            )
        except GitHubOAuthError as exc:
            raise GitHubReauthRequiredError() from exc

        connection.access_token_encrypted = encrypt_secret(refreshed.access_token)
        if refreshed.refresh_token:
            connection.refresh_token_encrypted = encrypt_secret(refreshed.refresh_token)
        connection.access_token_expires_at = refreshed.expires_at
        await db.flush()
        access_token = refreshed.access_token

    client = get_github_client(access_token)
    if client is None:
        raise GitHubNotConnectedError()
    return client


async def list_tracked_repos(db: AsyncSession, workspace_id: uuid.UUID) -> list[GitHubTrackedRepo]:
    return list(
        (
            await db.execute(
                select(GitHubTrackedRepo)
                .where(GitHubTrackedRepo.workspace_id == workspace_id)
                .order_by(GitHubTrackedRepo.full_name)
            )
        )
        .scalars()
        .all()
    )


async def get_tracked_repo(
    db: AsyncSession, workspace_id: uuid.UUID, repo_id: int
) -> GitHubTrackedRepo:
    repo = (
        await db.execute(
            select(GitHubTrackedRepo).where(
                GitHubTrackedRepo.workspace_id == workspace_id,
                GitHubTrackedRepo.repo_id == repo_id,
            )
        )
    ).scalar_one_or_none()
    if repo is None:
        raise RepoNotTrackedError()
    return repo


async def track_repo(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    repo_id: int,
    owner: str,
    name: str,
) -> GitHubTrackedRepo:
    existing = (
        await db.execute(
            select(GitHubTrackedRepo).where(
                GitHubTrackedRepo.workspace_id == workspace_id,
                GitHubTrackedRepo.repo_id == repo_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise RepoAlreadyTrackedError()

    repo = GitHubTrackedRepo(
        workspace_id=workspace_id,
        repo_id=repo_id,
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        added_by_id=user_id,
    )
    db.add(repo)
    await db.flush()
    return repo


async def untrack_repo(db: AsyncSession, workspace_id: uuid.UUID, repo_id: int) -> bool:
    result = await db.execute(
        delete(GitHubTrackedRepo).where(
            GitHubTrackedRepo.workspace_id == workspace_id,
            GitHubTrackedRepo.repo_id == repo_id,
        )
    )
    await db.flush()
    return bool(result.rowcount)


def _prune_issue_cache(now: float) -> None:
    """Drop expired entries so the cache cannot grow without bound in a
    long-lived process."""
    for key, (stored_at, _) in list(_issue_cache.items()):
        if now - stored_at >= _ISSUE_CACHE_TTL_SECONDS:
            _issue_cache.pop(key, None)


async def _issues_for_repo(
    client: GitHubClient,
    repo: GitHubTrackedRepo,
    *,
    user_id: uuid.UUID,
    state: IssueState,
    assignee: str | None,
    labels: Sequence[str] | None,
    per_page: int,
) -> list[GitHubIssue]:
    cache_key = (
        user_id,
        repo.repo_id,
        state,
        assignee,
        tuple(labels or ()),
        per_page,
    )
    now = time.monotonic()
    cached = _issue_cache.get(cache_key)
    if cached is not None and now - cached[0] < _ISSUE_CACHE_TTL_SECONDS:
        return cached[1]
    _prune_issue_cache(now)

    issues = await client.list_issues(
        repo.owner,
        repo.name,
        state=state,
        assignee=assignee,
        labels=labels,
        per_page=per_page,
    )
    stamped = [
        replace(issue, repo_full_name=repo.full_name, repo_id=repo.repo_id) for issue in issues
    ]
    _issue_cache[cache_key] = (now, stamped)
    return stamped


def invalidate_repo_cache(repo_id: int) -> None:
    """Drop cached issues for one repository — called after creating an issue so
    the new one shows up immediately instead of after the TTL."""
    for key in [key for key in _issue_cache if key[1] == repo_id]:
        _issue_cache.pop(key, None)


async def list_workspace_issues(
    db: AsyncSession,
    client: GitHubClient,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    state: IssueState = "open",
    assignee: str | None = None,
    labels: Sequence[str] | None = None,
    repo_ids: Sequence[int] | None = None,
    per_page: int = 50,
) -> IssueListing:
    """Issues across the workspace's tracked repositories, newest activity first.

    Repositories are fetched concurrently and failures are collected per
    repository rather than raised: a board with one broken repo should still
    render the other four.
    """
    repos = await list_tracked_repos(db, workspace_id)
    if repo_ids:
        wanted = set(repo_ids)
        repos = [repo for repo in repos if repo.repo_id in wanted]
    if not repos:
        return IssueListing(issues=[], failures=[])

    results = await asyncio.gather(
        *(
            _issues_for_repo(
                client,
                repo,
                user_id=user_id,
                state=state,
                assignee=assignee,
                labels=labels,
                per_page=per_page,
            )
            for repo in repos
        ),
        return_exceptions=True,
    )

    issues: list[GitHubIssue] = []
    failures: list[RepoFailure] = []
    for repo, result in zip(repos, results, strict=True):
        if isinstance(result, BaseException):
            if not isinstance(result, GitHubError):
                raise result
            failures.append(
                RepoFailure(repo_id=repo.repo_id, full_name=repo.full_name, message=str(result))
            )
            continue
        issues.extend(result)

    issues.sort(key=lambda issue: issue.updated_at, reverse=True)
    return IssueListing(issues=issues, failures=failures)


async def create_issue(
    db: AsyncSession,
    client: GitHubClient,
    workspace_id: uuid.UUID,
    *,
    repo_id: int,
    title: str,
    body: str | None,
    assignees: Sequence[str],
    labels: Sequence[str],
) -> GitHubIssue:
    repo = await get_tracked_repo(db, workspace_id, repo_id)

    issue = await client.create_issue(
        repo.owner,
        repo.name,
        title=title,
        body=body,
        assignees=assignees,
        labels=labels,
    )
    invalidate_repo_cache(repo_id)
    return replace(issue, repo_full_name=repo.full_name, repo_id=repo.repo_id)


async def move_issue(
    db: AsyncSession,
    client: GitHubClient,
    workspace_id: uuid.UUID,
    *,
    repo_id: int,
    number: int,
    lane: str,
    assignees: Sequence[str],
) -> GitHubIssue:
    """Persist a lane transition using GitHub's real issue fields."""
    repo = await get_tracked_repo(db, workspace_id, repo_id)
    if lane == LANE_IN_PROGRESS and not assignees:
        raise ValueError("In-progress issues must have at least one assignee.")

    target_assignees = [] if lane == LANE_OPEN else assignees
    issue = await client.update_issue(
        repo.owner,
        repo.name,
        number,
        state="closed" if lane == LANE_DONE else "open",
        assignees=target_assignees,
    )
    invalidate_repo_cache(repo_id)
    return replace(issue, repo_full_name=repo.full_name, repo_id=repo.repo_id)


async def list_repo_labels(
    db: AsyncSession, client: GitHubClient, workspace_id: uuid.UUID, repo_id: int
) -> list[GitHubLabel]:
    repo = await get_tracked_repo(db, workspace_id, repo_id)
    return await client.list_repo_labels(repo.owner, repo.name)


async def list_repo_assignees(
    db: AsyncSession, client: GitHubClient, workspace_id: uuid.UUID, repo_id: int
) -> list[GitHubUser]:
    repo = await get_tracked_repo(db, workspace_id, repo_id)
    return await client.list_repo_assignees(repo.owner, repo.name)
