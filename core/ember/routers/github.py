import logging
import secrets
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env, github_configured
from ember.crypto import SecretDecryptionError, SecretEncryptionUnavailableError
from ember.db import get_db
from ember.dependencies import get_current_user
from ember.github import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubIssue,
    GitHubNotFoundError,
    GitHubOAuthError,
    GitHubRateLimitError,
    GitHubValidationError,
    IssueState,
    authorize_url,
    exchange_code,
    get_github_client,
)
from ember.jwt import create_oauth_state_token, decode_oauth_state_token
from ember.models import User
from ember.schemas.github import (
    GitHubAuthorizeResponse,
    GitHubIssueCreateRequest,
    GitHubIssueListResponse,
    GitHubIssueMoveRequest,
    GitHubIssueResponse,
    GitHubLabelResponse,
    GitHubRepoErrorResponse,
    GitHubRepoResponse,
    GitHubStatusResponse,
    GitHubTrackedRepoResponse,
    GitHubTrackRepoRequest,
    GitHubUserResponse,
)
from ember.services.github import (
    GitHubNotConnectedError,
    GitHubReauthRequiredError,
    RepoAlreadyTrackedError,
    RepoNotTrackedError,
    client_for_user,
    create_issue,
    disconnect,
    get_connection,
    issue_lane,
    list_repo_assignees,
    list_repo_labels,
    list_tracked_repos,
    list_workspace_issues,
    move_issue,
    track_repo,
    untrack_repo,
    upsert_connection,
)
from ember.services.workspaces import NotAWorkspaceMemberError, assert_workspace_member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["GitHub"])

OAUTH_PROVIDER = "github"
OAUTH_STATE_COOKIE = "github_oauth_state"
OAUTH_STATE_COOKIE_PATH = "/api/integrations/github"

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _callback_url() -> str:
    """Where GitHub sends the browser back to. Must match the OAuth App's
    registered callback exactly, and is sent again at token exchange because
    GitHub verifies the two agree."""
    return f"{env['PUBLIC_APP_URL'].rstrip('/')}/api/integrations/github/callback"


def _redirect_to_settings(outcome: str) -> RedirectResponse:
    base = env["PUBLIC_APP_URL"].rstrip("/")
    response = RedirectResponse(
        url=f"{base}/settings?github={outcome}", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_COOKIE_PATH)
    return response


def _require_configured() -> None:
    if not github_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The GitHub integration is not configured on this server.",
        )


async def _require_membership(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    try:
        await assert_workspace_member(db, workspace_id, user_id)
    except NotAWorkspaceMemberError as exc:
        raise _NOT_FOUND from exc


def _github_http_error(exc: GitHubError) -> HTTPException:
    """Translate a provider failure into a status the frontend can act on."""
    if isinstance(exc, GitHubAuthError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub rejected the stored token. Reconnect your GitHub account.",
        )
    if isinstance(exc, GitHubRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="GitHub rate limit exceeded."
        )
    if isinstance(exc, GitHubNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The GitHub resource was not found."
        )
    if isinstance(exc, GitHubValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"GitHub error: {exc}")


_NOT_CONNECTED = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="No GitHub account is connected. Connect one in Settings.",
)


def _connection_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GitHubReauthRequiredError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The GitHub connection expired. Reconnect your GitHub account.",
        )
    if isinstance(exc, SecretDecryptionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The stored GitHub token could not be read. Reconnect your GitHub account.",
        )
    return _NOT_CONNECTED


async def _require_github_client(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GitHubClient:
    try:
        return await client_for_user(db, user.id)
    except (GitHubNotConnectedError, GitHubReauthRequiredError, SecretDecryptionError) as exc:
        raise _connection_http_error(exc) from exc


def _issue_response(issue: GitHubIssue) -> GitHubIssueResponse:
    return GitHubIssueResponse(
        id=issue.id,
        number=issue.number,
        title=issue.title,
        body=issue.body,
        state=issue.state,
        state_reason=issue.state_reason,
        html_url=issue.html_url,
        lane=issue_lane(issue),
        assignees=[
            GitHubUserResponse(login=user.login, avatar_url=user.avatar_url, name=user.name)
            for user in issue.assignees
        ],
        labels=[
            GitHubLabelResponse(name=label.name, color=label.color, description=label.description)
            for label in issue.labels
        ],
        comments=issue.comments,
        author=(
            GitHubUserResponse(
                login=issue.author.login, avatar_url=issue.author.avatar_url, name=issue.author.name
            )
            if issue.author
            else None
        ),
        milestone=issue.milestone,
        repo_id=issue.repo_id,
        repo_full_name=issue.repo_full_name,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        closed_at=issue.closed_at,
    )


@router.get("/integrations/github/status")
async def github_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GitHubStatusResponse:
    connection = await get_connection(db, user.id)
    if connection is None:
        return GitHubStatusResponse(configured=github_configured(), connected=False)
    return GitHubStatusResponse(
        configured=github_configured(),
        connected=True,
        login=connection.github_login,
        avatar_url=connection.avatar_url,
        scopes=connection.scopes,
        connected_at=connection.connected_at,
    )


@router.get("/integrations/github/authorize")
async def github_authorize(
    response: Response,
    user: User = Depends(get_current_user),
) -> GitHubAuthorizeResponse:
    """Start the handshake.

    Returns the URL as JSON rather than issuing a redirect: the caller is a
    fetch() from an already-authenticated page, and a 302 would be followed by
    the XHR instead of the browser's address bar.
    """
    _require_configured()

    state = create_oauth_state_token(user_id=user.id, provider=OAUTH_PROVIDER)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
        max_age=10 * 60,
    )
    return GitHubAuthorizeResponse(url=authorize_url(state=state, redirect_uri=_callback_url()))


@router.get("/integrations/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    _require_configured()

    if error:
        logger.info("GitHub OAuth denied by user: %s", error)
        return _redirect_to_settings("denied")

    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not cookie_state:
        return _redirect_to_settings("invalid_state")

    if not secrets.compare_digest(state, cookie_state):
        return _redirect_to_settings("invalid_state")

    try:
        user_id = decode_oauth_state_token(state, provider=OAUTH_PROVIDER)
    except jwt.PyJWTError:
        return _redirect_to_settings("invalid_state")

    try:
        token = await exchange_code(code=code, redirect_uri=_callback_url())
    except GitHubOAuthError:
        logger.exception("GitHub OAuth token exchange failed")
        return _redirect_to_settings("error")

    client = get_github_client(token.access_token)
    if client is None:
        return _redirect_to_settings("error")

    try:
        viewer = await client.get_viewer()
    except GitHubError:
        logger.exception("Could not read the GitHub account after token exchange")
        return _redirect_to_settings("error")

    try:
        await upsert_connection(db, user_id, token=token, viewer=viewer)
    except SecretEncryptionUnavailableError:
        logger.exception("GitHub token could not be encrypted")
        return _redirect_to_settings("error")

    return _redirect_to_settings("connected")


@router.delete("/integrations/github/connection", status_code=status.HTTP_204_NO_CONTENT)
async def github_disconnect(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if not await disconnect(db, user.id):
        raise _NOT_CONNECTED


@router.get("/integrations/github/repos")
async def github_repos(
    workspace_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> list[GitHubRepoResponse]:
    """Repositories the connected account can reach, for the tracking picker.

    `workspace_id` is optional and only marks which are already tracked, so the
    picker can show the current state without a second round-trip.
    """
    tracked_ids: set[int] = set()
    if workspace_id is not None:
        await _require_membership(db, workspace_id, user.id)
        tracked_ids = {repo.repo_id for repo in await list_tracked_repos(db, workspace_id)}

    try:
        repos = await client.list_accessible_repos(query=q)
    except GitHubError as exc:
        raise _github_http_error(exc) from exc

    return [
        GitHubRepoResponse(
            id=repo.id,
            owner=repo.owner,
            name=repo.name,
            full_name=repo.full_name,
            private=repo.private,
            html_url=repo.html_url,
            description=repo.description,
            is_organization=repo.is_organization,
            open_issues_count=repo.open_issues_count,
            tracked=repo.id in tracked_ids,
        )
        for repo in repos
    ]


def _tracked_response(repo) -> GitHubTrackedRepoResponse:
    return GitHubTrackedRepoResponse(
        id=str(repo.id),
        workspace_id=str(repo.workspace_id),
        repo_id=repo.repo_id,
        owner=repo.owner,
        name=repo.name,
        full_name=repo.full_name,
        created_at=repo.created_at,
    )


@router.get("/workspaces/{workspace_id}/github/repos")
async def list_workspace_repos(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GitHubTrackedRepoResponse]:
    await _require_membership(db, workspace_id, user.id)
    return [_tracked_response(repo) for repo in await list_tracked_repos(db, workspace_id)]


@router.post("/workspaces/{workspace_id}/github/repos", status_code=status.HTTP_201_CREATED)
async def track_workspace_repo(
    workspace_id: uuid.UUID,
    data: GitHubTrackRepoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GitHubTrackedRepoResponse:
    await _require_membership(db, workspace_id, user.id)
    try:
        repo = await track_repo(
            db,
            workspace_id,
            user.id,
            repo_id=data.repo_id,
            owner=data.owner,
            name=data.name,
        )
    except RepoAlreadyTrackedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This repository is already tracked."
        ) from exc
    return _tracked_response(repo)


@router.delete(
    "/workspaces/{workspace_id}/github/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def untrack_workspace_repo(
    workspace_id: uuid.UUID,
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await _require_membership(db, workspace_id, user.id)
    if not await untrack_repo(db, workspace_id, repo_id):
        raise _NOT_FOUND


@router.get("/workspaces/{workspace_id}/github/repos/{repo_id}/labels")
async def workspace_repo_labels(
    workspace_id: uuid.UUID,
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> list[GitHubLabelResponse]:
    await _require_membership(db, workspace_id, user.id)
    try:
        labels = await list_repo_labels(db, client, workspace_id, repo_id)
    except RepoNotTrackedError as exc:
        raise _NOT_FOUND from exc
    except GitHubError as exc:
        raise _github_http_error(exc) from exc
    return [
        GitHubLabelResponse(name=label.name, color=label.color, description=label.description)
        for label in labels
    ]


@router.get("/workspaces/{workspace_id}/github/repos/{repo_id}/assignees")
async def workspace_repo_assignees(
    workspace_id: uuid.UUID,
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> list[GitHubUserResponse]:
    await _require_membership(db, workspace_id, user.id)
    try:
        users = await list_repo_assignees(db, client, workspace_id, repo_id)
    except RepoNotTrackedError as exc:
        raise _NOT_FOUND from exc
    except GitHubError as exc:
        raise _github_http_error(exc) from exc
    return [
        GitHubUserResponse(login=user.login, avatar_url=user.avatar_url, name=user.name)
        for user in users
    ]


## issues
@router.get("/workspaces/{workspace_id}/github/issues")
async def list_issues(
    workspace_id: uuid.UUID,
    state: IssueState = Query(default="open"),
    assignee: str | None = Query(default=None, max_length=120),
    labels: list[str] | None = Query(default=None),
    repo_id: list[int] | None = Query(default=None),
    per_page: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> GitHubIssueListResponse:
    await _require_membership(db, workspace_id, user.id)

    try:
        listing = await list_workspace_issues(
            db,
            client,
            user.id,
            workspace_id,
            state=state,
            assignee=assignee,
            labels=labels,
            repo_ids=repo_id,
            per_page=per_page,
        )
    except GitHubError as exc:
        raise _github_http_error(exc) from exc

    return GitHubIssueListResponse(
        issues=[_issue_response(issue) for issue in listing.issues],
        repo_errors=[
            GitHubRepoErrorResponse(
                repo_id=failure.repo_id, full_name=failure.full_name, message=failure.message
            )
            for failure in listing.failures
        ],
    )


@router.post("/workspaces/{workspace_id}/github/issues", status_code=status.HTTP_201_CREATED)
async def create_workspace_issue(
    workspace_id: uuid.UUID,
    data: GitHubIssueCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> GitHubIssueResponse:
    await _require_membership(db, workspace_id, user.id)

    try:
        issue = await create_issue(
            db,
            client,
            workspace_id,
            repo_id=data.repo_id,
            title=data.title,
            body=data.body,
            assignees=data.assignees,
            labels=data.labels,
        )
    except RepoNotTrackedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That repository is not tracked by this workspace.",
        ) from exc
    except GitHubError as exc:
        raise _github_http_error(exc) from exc

    return _issue_response(issue)


@router.patch("/workspaces/{workspace_id}/github/issues/{repo_id}/{number}")
async def move_workspace_issue(
    workspace_id: uuid.UUID,
    repo_id: int,
    number: int,
    data: GitHubIssueMoveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GitHubClient = Depends(_require_github_client),
) -> GitHubIssueResponse:
    await _require_membership(db, workspace_id, user.id)

    try:
        issue = await move_issue(
            db,
            client,
            workspace_id,
            repo_id=repo_id,
            number=number,
            lane=data.lane,
            assignees=data.assignees,
        )
    except RepoNotTrackedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That repository is not tracked by this workspace.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except GitHubError as exc:
        raise _github_http_error(exc) from exc

    return _issue_response(issue)
