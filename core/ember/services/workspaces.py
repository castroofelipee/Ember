import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import UserPreferences, Workspace, WorkspaceMember, WorkspaceRole
from ember.schemas.workspaces import WorkspaceCreateRequest


class NotAWorkspaceMemberError(Exception):
    """Raised when the current user has no WorkspaceMember row for the given
    workspace — surfaced as 404, not 403, so a non-member can't even confirm
    the workspace id exists."""


async def create_workspace(
    session: AsyncSession, owner_id: uuid.UUID, data: WorkspaceCreateRequest
) -> Workspace:
    workspace = Workspace(name=data.name)
    session.add(workspace)
    await session.flush()

    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=owner_id, role=WorkspaceRole.OWNER)
    )
    # Each workspace gets its own schedule/settings for the member, rather than
    # inheriting one global configuration shared across every workspace.
    session.add(UserPreferences(user_id=owner_id, workspace_id=workspace.id))
    await session.flush()
    return workspace


async def list_my_workspaces(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Workspace, WorkspaceRole]]:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at)
        )
    ).all()
    return [(workspace, role) for workspace, role in rows]


async def assert_workspace_member(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotAWorkspaceMemberError()
