import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import WorkspaceRole
from ember.schemas.auth import SignupRequest
from ember.schemas.workspaces import WorkspaceCreateRequest
from ember.services.auth import signup
from ember.services.invites import create_invite
from ember.services.workspaces import (
    NotAWorkspaceMemberError,
    assert_workspace_member,
    create_workspace,
    list_my_workspaces,
)


async def _create_user(db_session: AsyncSession, *, inviter_id=None, **overrides: object):
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    if inviter_id is not None:
        _, data["invite_code"] = await create_invite(db_session, inviter_id)
    user, _, _ = await signup(db_session, SignupRequest(**data))
    return user


async def test_create_workspace_makes_creator_the_owner(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    workspace = await create_workspace(db_session, user.id, WorkspaceCreateRequest(name="Home"))

    rows = await list_my_workspaces(db_session, user.id)
    assert len(rows) == 1
    listed_workspace, role = rows[0]
    assert listed_workspace.id == workspace.id
    assert role == WorkspaceRole.OWNER


async def test_list_my_workspaces_excludes_others(db_session: AsyncSession) -> None:
    user_a = await _create_user(db_session)
    user_b = await _create_user(
        db_session, inviter_id=user_a.id, email="grace@example.com", display_name="Grace"
    )

    await create_workspace(db_session, user_a.id, WorkspaceCreateRequest(name="Home"))
    await create_workspace(db_session, user_b.id, WorkspaceCreateRequest(name="Work"))

    rows_a = await list_my_workspaces(db_session, user_a.id)
    assert [w.name for w, _ in rows_a] == ["Home"]


async def test_assert_workspace_member_passes_for_member(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    workspace = await create_workspace(db_session, user.id, WorkspaceCreateRequest(name="Home"))

    await assert_workspace_member(db_session, workspace.id, user.id)  # must not raise


async def test_assert_workspace_member_raises_for_non_member(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    outsider = await _create_user(
        db_session, inviter_id=owner.id, email="grace@example.com", display_name="Grace"
    )
    workspace = await create_workspace(db_session, owner.id, WorkspaceCreateRequest(name="Home"))

    with pytest.raises(NotAWorkspaceMemberError):
        await assert_workspace_member(db_session, workspace.id, outsider.id)


async def test_workspace_name_is_trimmed(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    workspace = await create_workspace(
        db_session, user.id, WorkspaceCreateRequest(name="  Home  ")
    )
    assert workspace.name == "Home"
