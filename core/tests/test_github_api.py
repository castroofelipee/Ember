import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from ember.config import env
from ember.github import (
    GitHubClient,
    GitHubIssue,
    GitHubLabel,
    GitHubRateLimitError,
    GitHubRepo,
    GitHubUser,
    IssueState,
)
from ember.github.client import _parse_issue
from ember.jwt import OAUTH_STATE_TYP, create_oauth_state_token
from ember.main import app
from ember.routers.github import OAUTH_STATE_COOKIE, _require_github_client
from ember.services.github import _issue_cache

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"
WORKSPACES_URL = "/api/workspaces"
CALLBACK_URL = "/api/integrations/github/callback"
STATUS_URL = "/api/integrations/github/status"


@pytest.fixture(autouse=True)
def _clear_issue_cache():
    """The issue cache is module-level and would otherwise leak between tests."""
    _issue_cache.clear()
    yield
    _issue_cache.clear()


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient, **overrides: object) -> str:
    response = await client.post(SIGNUP_URL, json=_signup_payload(**overrides))
    return response.json()["access_token"]


async def _signup_second_user(client: AsyncClient, inviter_token: str) -> str:
    invite = await client.post(INVITES_URL, headers=_auth_header(inviter_token))
    payload = _signup_payload(email="grace@example.com", display_name="Grace Hopper")
    payload["invite_code"] = invite.json()["code"]
    response = await client.post(SIGNUP_URL, json=payload)
    return response.json()["access_token"]


async def _make_workspace(client: AsyncClient, token: str, name: str = "Home") -> str:
    response = await client.post(WORKSPACES_URL, headers=_auth_header(token), json={"name": name})
    return response.json()["id"]


async def _track_repo(
    client: AsyncClient,
    token: str,
    workspace_id: str,
    *,
    repo_id: int = 101,
    owner: str = "acme",
    name: str = "rocket",
) -> dict:
    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos",
        headers=_auth_header(token),
        json={"repo_id": repo_id, "owner": owner, "name": name},
    )
    return response.json()


def _issue_payload(**overrides: object) -> dict:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "id": 1,
        "number": 1,
        "title": "Something is broken",
        "body": "Steps to reproduce",
        "state": "open",
        "html_url": "https://github.com/acme/rocket/issues/1",
        "assignees": [],
        "labels": [],
        "comments": 0,
        "created_at": now,
        "updated_at": now,
        "user": {"id": 9, "login": "ada", "avatar_url": None},
    }
    payload.update(overrides)
    return payload


def _make_issue(**overrides: object) -> GitHubIssue:
    return _parse_issue(_issue_payload(**overrides))


class FakeGitHubClient(GitHubClient):
    """In-memory GitHubClient. Records calls so tests can assert on what was
    actually sent to the provider."""

    def __init__(
        self,
        *,
        issues: dict[str, list[GitHubIssue]] | None = None,
        repos: list[GitHubRepo] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.issues = issues or {}
        self.repos = repos or []
        self.errors = errors or {}
        self.created: list[dict] = []
        self.list_calls: list[dict] = []

    async def get_viewer(self) -> GitHubUser:
        return GitHubUser(id=9, login="ada", avatar_url=None)

    async def list_accessible_repos(self, *, query: str | None = None) -> list[GitHubRepo]:
        if query:
            needle = query.lower()
            return [repo for repo in self.repos if needle in repo.full_name.lower()]
        return list(self.repos)

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
        key = f"{owner}/{repo}"
        self.list_calls.append({"repo": key, "state": state, "assignee": assignee, "labels": labels})
        if key in self.errors:
            raise self.errors[key]
        return list(self.issues.get(key, []))

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
        self.created.append(
            {
                "repo": f"{owner}/{repo}",
                "title": title,
                "body": body,
                "assignees": list(assignees or []),
                "labels": list(labels or []),
            }
        )
        return _make_issue(
            id=500,
            number=42,
            title=title,
            body=body,
            assignees=[{"id": 1, "login": login} for login in assignees or []],
            labels=[{"name": name, "color": "d73a4a"} for name in labels or []],
        )

    async def list_repo_labels(self, owner: str, repo: str) -> list[GitHubLabel]:
        return [GitHubLabel(name="bug", color="d73a4a", description="Broken")]

    async def list_repo_assignees(self, owner: str, repo: str) -> list[GitHubUser]:
        return [GitHubUser(id=9, login="ada", avatar_url=None)]


def _use_fake_client(fake: FakeGitHubClient) -> None:
    app.dependency_overrides[_require_github_client] = lambda: fake


async def test_status_reports_not_connected_for_a_fresh_account(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.get(STATUS_URL, headers=_auth_header(token))

    assert response.status_code == 200
    assert response.json()["connected"] is False


async def test_status_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(STATUS_URL)

    assert response.status_code == 401


async def test_disconnect_without_a_connection_is_a_conflict(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.delete(
        "/api/integrations/github/connection", headers=_auth_header(token)
    )

    assert response.status_code == 409



async def test_callback_without_state_is_rejected(client: AsyncClient) -> None:
    response = await client.get(CALLBACK_URL, params={"code": "abc"}, follow_redirects=False)

    assert response.status_code == 302
    assert "github=invalid_state" in response.headers["location"]


async def test_callback_rejects_a_state_that_does_not_match_the_cookie(
    client: AsyncClient,
) -> None:
    """The state is what proves which user began the flow, so a query parameter
    that disagrees with the cookie must never reach the token exchange."""
    mine = create_oauth_state_token(user_id=uuid.uuid4(), provider="github")
    theirs = create_oauth_state_token(user_id=uuid.uuid4(), provider="github")
    client.cookies.set(OAUTH_STATE_COOKIE, mine, domain="test", path="/api/integrations/github")

    response = await client.get(
        CALLBACK_URL, params={"code": "abc", "state": theirs}, follow_redirects=False
    )

    assert response.status_code == 302
    assert "github=invalid_state" in response.headers["location"]
    client.cookies.clear()


async def test_callback_rejects_a_state_minted_for_another_provider(
    client: AsyncClient,
) -> None:
    state = create_oauth_state_token(user_id=uuid.uuid4(), provider="gitlab")
    client.cookies.set(OAUTH_STATE_COOKIE, state, domain="test", path="/api/integrations/github")

    response = await client.get(
        CALLBACK_URL, params={"code": "abc", "state": state}, follow_redirects=False
    )

    assert response.status_code == 302
    assert "github=invalid_state" in response.headers["location"]
    client.cookies.clear()


async def test_callback_rejects_an_expired_state(client: AsyncClient) -> None:
    """State tokens live ten minutes; an old one must not still open a session."""
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": OAUTH_STATE_TYP,
            "provider": "github",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        env["JWT_SECRET_KEY"],
        algorithm="HS256",
    )
    client.cookies.set(OAUTH_STATE_COOKIE, expired, domain="test", path="/api/integrations/github")

    response = await client.get(
        CALLBACK_URL, params={"code": "abc", "state": expired}, follow_redirects=False
    )

    assert response.status_code == 302
    assert "github=invalid_state" in response.headers["location"]
    client.cookies.clear()


async def test_callback_reports_a_denied_authorization(client: AsyncClient) -> None:
    response = await client.get(
        CALLBACK_URL, params={"error": "access_denied"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert "github=denied" in response.headers["location"]


async def test_authorize_sets_the_state_cookie_and_returns_github_url(
    client: AsyncClient,
) -> None:
    token = await _signup(client)

    response = await client.get(
        "/api/integrations/github/authorize", headers=_auth_header(token)
    )

    assert response.status_code == 200
    url = response.json()["url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "scope=repo+read%3Aorg" in url
    cookie = response.cookies.get(OAUTH_STATE_COOKIE)
    assert cookie is not None
    assert f"state={cookie}" in url
    client.cookies.clear()


async def test_track_and_list_repositories(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    tracked = await _track_repo(client, token, workspace_id)
    assert tracked["full_name"] == "acme/rocket"

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos", headers=_auth_header(token)
    )
    assert listed.status_code == 200
    assert [repo["full_name"] for repo in listed.json()] == ["acme/rocket"]


async def test_tracking_the_same_repository_twice_is_a_conflict(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos",
        headers=_auth_header(token),
        json={"repo_id": 101, "owner": "acme", "name": "rocket"},
    )

    assert response.status_code == 409


async def test_untrack_removes_the_repository(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)

    deleted = await client.delete(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos/101", headers=_auth_header(token)
    )
    assert deleted.status_code == 204

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos", headers=_auth_header(token)
    )
    assert listed.json() == []


async def test_untracking_an_unknown_repository_is_a_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.delete(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos/999", headers=_auth_header(token)
    )

    assert response.status_code == 404


async def test_non_members_cannot_see_or_track_repositories(client: AsyncClient) -> None:
    """A non-member gets 404, not 403 — they should not even be able to confirm
    the workspace exists (services/workspaces.py)."""
    owner_token = await _signup(client)
    workspace_id = await _make_workspace(client, owner_token)
    await _track_repo(client, owner_token, workspace_id)
    outsider_token = await _signup_second_user(client, owner_token)

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos", headers=_auth_header(outsider_token)
    )
    tracked = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos",
        headers=_auth_header(outsider_token),
        json={"repo_id": 202, "owner": "acme", "name": "other"},
    )

    assert listed.status_code == 404
    assert tracked.status_code == 404


async def test_tracked_repositories_are_scoped_to_one_workspace(client: AsyncClient) -> None:
    token = await _signup(client)
    first = await _make_workspace(client, token, "First")
    second = await _make_workspace(client, token, "Second")
    await _track_repo(client, token, first)

    listed = await client.get(
        f"{WORKSPACES_URL}/{second}/github/repos", headers=_auth_header(token)
    )

    assert listed.json() == []



async def test_issues_are_empty_when_no_repository_is_tracked(client: AsyncClient) -> None:
    """No tracked repos means no call reaches the provider — the response is an
    empty board, not an error."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    _use_fake_client(FakeGitHubClient())

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(token)
    )

    assert response.status_code == 200
    assert response.json() == {"issues": [], "repo_errors": []}


async def test_issues_merge_across_repositories_newest_first(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id, repo_id=101, owner="acme", name="rocket")
    await _track_repo(client, token, workspace_id, repo_id=202, owner="acme", name="probe")

    older = (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    newer = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _use_fake_client(
        FakeGitHubClient(
            issues={
                "acme/rocket": [_make_issue(id=1, number=1, title="Old", updated_at=older)],
                "acme/probe": [_make_issue(id=2, number=2, title="New", updated_at=newer)],
            }
        )
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(token)
    )

    assert response.status_code == 200
    issues = response.json()["issues"]
    assert [issue["title"] for issue in issues] == ["New", "Old"]
    assert {issue["repo_full_name"] for issue in issues} == {"acme/rocket", "acme/probe"}


async def test_pull_requests_are_not_listed_as_issues() -> None:
    """GitHub's issues endpoint returns pull requests too. The seam drops them
    so no caller has to remember to."""
    from ember.github.client import RestGitHubClient, _PULL_REQUEST_KEY

    raw = [
        _issue_payload(id=1, number=1, title="A real issue"),
        _issue_payload(id=2, number=2, title="A pull request", **{_PULL_REQUEST_KEY: {"url": "x"}}),
    ]
    parsed = [_parse_issue(item) for item in raw if _PULL_REQUEST_KEY not in item]

    assert [issue.title for issue in parsed] == ["A real issue"]
    assert hasattr(RestGitHubClient, "list_issues")


async def test_lanes_are_derived_from_state_and_assignment(client: AsyncClient) -> None:
    """GitHub has no "in progress" state; assignment is the proxy the UI shows."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    _use_fake_client(
        FakeGitHubClient(
            issues={
                "acme/rocket": [
                    _make_issue(id=1, number=1, title="Unassigned", state="open"),
                    _make_issue(
                        id=2,
                        number=2,
                        title="Assigned",
                        state="open",
                        assignees=[{"id": 9, "login": "ada"}],
                    ),
                    _make_issue(id=3, number=3, title="Closed", state="closed"),
                ]
            }
        )
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        params={"state": "all"},
        headers=_auth_header(token),
    )

    lanes = {issue["title"]: issue["lane"] for issue in response.json()["issues"]}
    assert lanes == {"Unassigned": "open", "Assigned": "in_progress", "Closed": "done"}


async def test_one_failing_repository_does_not_blank_the_board(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id, repo_id=101, owner="acme", name="rocket")
    await _track_repo(client, token, workspace_id, repo_id=202, owner="acme", name="probe")
    _use_fake_client(
        FakeGitHubClient(
            issues={"acme/rocket": [_make_issue(title="Still here")]},
            errors={"acme/probe": GitHubRateLimitError("GitHub rate limit exceeded.")},
        )
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert [issue["title"] for issue in body["issues"]] == ["Still here"]
    assert [error["full_name"] for error in body["repo_errors"]] == ["acme/probe"]


async def test_issue_filters_reach_the_provider(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    fake = FakeGitHubClient(issues={"acme/rocket": []})
    _use_fake_client(fake)

    await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        params={"state": "closed", "assignee": "ada", "labels": ["bug"]},
        headers=_auth_header(token),
    )

    assert fake.list_calls[0]["state"] == "closed"
    assert fake.list_calls[0]["assignee"] == "ada"
    assert list(fake.list_calls[0]["labels"]) == ["bug"]


async def test_repo_id_filter_narrows_to_one_repository(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id, repo_id=101, owner="acme", name="rocket")
    await _track_repo(client, token, workspace_id, repo_id=202, owner="acme", name="probe")
    fake = FakeGitHubClient(issues={"acme/rocket": [], "acme/probe": []})
    _use_fake_client(fake)

    await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        params={"repo_id": [202]},
        headers=_auth_header(token),
    )

    assert [call["repo"] for call in fake.list_calls] == ["acme/probe"]


async def test_non_members_cannot_read_issues(client: AsyncClient) -> None:
    owner_token = await _signup(client)
    workspace_id = await _make_workspace(client, owner_token)
    await _track_repo(client, owner_token, workspace_id)
    outsider_token = await _signup_second_user(client, owner_token)
    _use_fake_client(FakeGitHubClient())

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(outsider_token)
    )

    assert response.status_code == 404


async def test_create_issue_sends_title_body_assignees_and_labels(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    fake = FakeGitHubClient()
    _use_fake_client(fake)

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        headers=_auth_header(token),
        json={
            "repo_id": 101,
            "title": "Ship the thing",
            "body": "Details here",
            "assignees": ["ada"],
            "labels": ["bug"],
        },
    )

    assert response.status_code == 201
    assert fake.created == [
        {
            "repo": "acme/rocket",
            "title": "Ship the thing",
            "body": "Details here",
            "assignees": ["ada"],
            "labels": ["bug"],
        }
    ]
    body = response.json()
    assert body["number"] == 42
    assert body["repo_full_name"] == "acme/rocket"


async def test_create_issue_rejects_an_untracked_repository(client: AsyncClient) -> None:
    """The tracked table is the allowlist — a member must not be able to aim the
    workspace's token at an arbitrary repository."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    fake = FakeGitHubClient()
    _use_fake_client(fake)

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        headers=_auth_header(token),
        json={"repo_id": 999, "title": "Sneaky"},
    )

    assert response.status_code == 404
    assert fake.created == []


async def test_create_issue_rejects_a_blank_title(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    _use_fake_client(FakeGitHubClient())

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        headers=_auth_header(token),
        json={"repo_id": 101, "title": "   "},
    )

    assert response.status_code == 422


async def test_create_issue_invalidates_the_cached_listing(client: AsyncClient) -> None:
    """A newly filed issue has to show up straight away, not after the TTL."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    fake = FakeGitHubClient(issues={"acme/rocket": []})
    _use_fake_client(fake)

    await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(token)
    )
    fake.issues["acme/rocket"] = [_make_issue(title="Just filed")]
    await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        headers=_auth_header(token),
        json={"repo_id": 101, "title": "Just filed"},
    )
    after = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues", headers=_auth_header(token)
    )

    assert [issue["title"] for issue in after.json()["issues"]] == ["Just filed"]


async def test_non_members_cannot_create_issues(client: AsyncClient) -> None:
    owner_token = await _signup(client)
    workspace_id = await _make_workspace(client, owner_token)
    await _track_repo(client, owner_token, workspace_id)
    outsider_token = await _signup_second_user(client, owner_token)
    fake = FakeGitHubClient()
    _use_fake_client(fake)

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/github/issues",
        headers=_auth_header(outsider_token),
        json={"repo_id": 101, "title": "Not mine"},
    )

    assert response.status_code == 404
    assert fake.created == []



async def test_labels_and_assignees_come_from_the_tracked_repository(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await _track_repo(client, token, workspace_id)
    _use_fake_client(FakeGitHubClient())

    labels = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos/101/labels", headers=_auth_header(token)
    )
    assignees = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos/101/assignees", headers=_auth_header(token)
    )

    assert labels.json() == [{"name": "bug", "color": "d73a4a", "description": "Broken"}]
    assert [user["login"] for user in assignees.json()] == ["ada"]


async def test_labels_for_an_untracked_repository_are_a_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    _use_fake_client(FakeGitHubClient())

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/github/repos/999/labels", headers=_auth_header(token)
    )

    assert response.status_code == 404
