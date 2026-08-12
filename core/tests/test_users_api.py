import pytest
from httpx import AsyncClient

from ember.config import env
from ember.routers import users

ME_URL = "/api/users/me"
AVATAR_URL = "/api/users/me/avatar"
# A one-pixel PNG — small enough to inline, real enough to carry an image/* type.
PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


async def _signup(client: AsyncClient) -> str:
    response = await client.post(
        "/api/auth/signup",
        json={
            "email": "avatar@example.com",
            "password": "correct horse battery",
            "display_name": "Ada Lovelace",
        },
    )
    return response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cloudinary_stub(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stands in for the Cloudinary account the test environment does not have,
    recording the calls so tests can assert on what would have been uploaded.
    Only the network calls are faked — URL building runs for real, since the
    shape of the URL is part of what these tests check."""
    calls: list[dict] = []
    monkeypatch.setitem(env, "CLOUDINARY_URL", "cloudinary://key:secret@embertest")

    def fake_upload(contents: bytes, **options: object) -> dict:
        calls.append({"contents": contents, **options})
        return {"public_id": options["public_id"], "version": 1700000000 + len(calls)}

    def fake_destroy(public_id: str, **options: object) -> dict:
        calls.append({"destroyed": public_id, **options})
        return {"result": "ok"}

    monkeypatch.setattr(users.cloudinary.uploader, "upload", fake_upload)
    monkeypatch.setattr(users.cloudinary.uploader, "destroy", fake_destroy)
    return calls


async def test_read_current_user_requires_auth(client: AsyncClient) -> None:
    response = await client.get(ME_URL)

    assert response.status_code == 401


async def test_read_current_user_returns_identity_without_avatar(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.get(ME_URL, headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "avatar@example.com"
    assert body["display_name"] == "Ada Lovelace"
    assert body["avatar_url"] is None


async def test_upload_avatar_requires_auth(client: AsyncClient) -> None:
    response = await client.post(AVATAR_URL, files={"file": ("me.png", PIXEL_PNG, "image/png")})

    assert response.status_code == 401


async def test_upload_avatar_rejects_non_image(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(
        AVATAR_URL,
        headers=_auth_header(token),
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


async def test_upload_avatar_without_cloudinary_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(env, "CLOUDINARY_URL", "")
    token = await _signup(client)

    response = await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("me.png", PIXEL_PNG, "image/png")}
    )

    assert response.status_code == 503


async def test_upload_avatar_stores_url_on_the_account(
    client: AsyncClient, cloudinary_stub: list[dict]
) -> None:
    token = await _signup(client)

    response = await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("me.png", PIXEL_PNG, "image/png")}
    )

    assert response.status_code == 200
    avatar_url = response.json()["avatar_url"]
    assert avatar_url.startswith("https://")
    assert "/users/" in avatar_url
    assert cloudinary_stub[0]["contents"] == PIXEL_PNG

    persisted = await client.get(ME_URL, headers=_auth_header(token))
    assert persisted.json()["avatar_url"] == avatar_url


async def test_replacing_avatar_overwrites_the_same_public_id_with_a_new_url(
    client: AsyncClient, cloudinary_stub: list[dict]
) -> None:
    token = await _signup(client)
    first = await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("me.png", PIXEL_PNG, "image/png")}
    )

    second = await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("new.png", PIXEL_PNG, "image/png")}
    )

    assert cloudinary_stub[0]["public_id"] == cloudinary_stub[1]["public_id"]
    assert cloudinary_stub[1]["overwrite"] is True
    # A stable public id would otherwise re-serve the old photo from cache.
    assert second.json()["avatar_url"] != first.json()["avatar_url"]


async def test_delete_avatar_clears_it_and_removes_the_upload(
    client: AsyncClient, cloudinary_stub: list[dict]
) -> None:
    token = await _signup(client)
    await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("me.png", PIXEL_PNG, "image/png")}
    )

    response = await client.delete(AVATAR_URL, headers=_auth_header(token))

    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert cloudinary_stub[-1]["destroyed"] == cloudinary_stub[0]["public_id"]


async def test_avatar_reaches_workspace_members(
    client: AsyncClient, cloudinary_stub: list[dict]
) -> None:
    token = await _signup(client)
    workspace = await client.post(
        "/api/workspaces", headers=_auth_header(token), json={"name": "Home"}
    )
    uploaded = await client.post(
        AVATAR_URL, headers=_auth_header(token), files={"file": ("me.png", PIXEL_PNG, "image/png")}
    )

    members = await client.get(
        f"/api/workspaces/{workspace.json()['id']}/members", headers=_auth_header(token)
    )

    assert members.json()[0]["avatar_url"] == uploaded.json()["avatar_url"]
