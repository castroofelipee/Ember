import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


_HEX_COLOR = re.compile(r"^[0-9a-fA-F]{6}$")
_DEFAULT_LABEL_COLOR = "ededed"


class GitHubStatusResponse(BaseModel):
    """Whether this user has connected GitHub, and who to."""

    configured: bool
    connected: bool
    login: str | None = None
    avatar_url: str | None = None
    scopes: str | None = None
    connected_at: datetime | None = None


class GitHubAuthorizeResponse(BaseModel):
    url: str


class GitHubUserResponse(BaseModel):
    login: str
    avatar_url: str | None = None
    name: str | None = None


class GitHubLabelResponse(BaseModel):
    name: str
    color: str
    description: str | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        stripped = value.strip().lstrip("#")
        if not _HEX_COLOR.match(stripped):
            return _DEFAULT_LABEL_COLOR
        return stripped.lower()


class GitHubRepoResponse(BaseModel):
    """A repository the connected account can reach — the picker's options."""

    id: int
    owner: str
    name: str
    full_name: str
    private: bool
    html_url: str
    description: str | None = None
    is_organization: bool
    open_issues_count: int = 0
    tracked: bool = False


class GitHubTrackedRepoResponse(BaseModel):
    id: str
    workspace_id: str
    repo_id: int
    owner: str
    name: str
    full_name: str
    created_at: datetime


class GitHubTrackRepoRequest(BaseModel):
    repo_id: int
    owner: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("owner", "name")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()


class GitHubIssueResponse(BaseModel):
    id: int
    number: int
    title: str
    body: str | None = None
    state: str
    state_reason: str | None = None
    html_url: str
    lane: str
    assignees: list[GitHubUserResponse]
    labels: list[GitHubLabelResponse]
    comments: int
    author: GitHubUserResponse | None = None
    milestone: str | None = None
    repo_id: int
    repo_full_name: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class GitHubRepoErrorResponse(BaseModel):
    repo_id: int
    full_name: str
    message: str


class GitHubIssueListResponse(BaseModel):
    issues: list[GitHubIssueResponse]
    repo_errors: list[GitHubRepoErrorResponse]


class GitHubIssueCreateRequest(BaseModel):
    repo_id: int
    title: str = Field(min_length=1, max_length=256)
    body: str | None = Field(default=None, max_length=65536)
    assignees: list[str] = Field(default_factory=list, max_length=10)
    labels: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be blank.")
        return stripped

    @field_validator("assignees", "labels")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            key = stripped.lower()
            if stripped and key not in seen:
                items.append(stripped)
                seen.add(key)
        return items
