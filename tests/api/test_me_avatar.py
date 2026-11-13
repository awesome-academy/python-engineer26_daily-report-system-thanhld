from pathlib import Path
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import (
    AVATAR_KEY_PREFIX,
    AVATAR_MAX_BYTES,
    IMAGE_SIGNATURES,
    ImageType,
)
from app.modules.users.models import User
from tests.factories import auth_headers, create_user

ME_URL = "/api/v1/me"
AVATAR_URL = "/api/v1/me/avatar"
PNG = IMAGE_SIGNATURES[ImageType.PNG] + b"anh-png"
JPEG = IMAGE_SIGNATURES[ImageType.JPEG] + b"\xe0anh-jpeg"


@pytest.fixture
def storage_dir() -> Path:
    # conftest trỏ LOCAL_STORAGE_DIR vào thư mục tạm; app lưu file thật vào đó.
    return get_settings().local_storage_dir


async def upload_avatar(
    client: AsyncClient,
    user: User,
    data: bytes,
    filename: str = "anh.png",
    content_type: str = "image/png",
) -> Response:
    return await client.put(
        AVATAR_URL, files={"file": (filename, data, content_type)}, headers=auth_headers(user)
    )


def base_url() -> str:
    return str(get_settings().local_storage_base_url).rstrip("/")


def stored_path(storage_dir: Path, avatar_url: str) -> Path:
    base_path = urlsplit(base_url()).path
    return storage_dir / urlsplit(avatar_url).path.removeprefix(f"{base_path}/")


@pytest.mark.parametrize(
    ("file", "extension"),
    [
        pytest.param(("anh.png", PNG, "image/png"), "png", id="png"),
        pytest.param(("anh.jpeg", JPEG, "image/jpeg"), "jpg", id="jpeg"),
        # Đuôi, Content-Type sai nhưng nội dung là PNG: xét theo nội dung, lưu đuôi đúng.
        pytest.param(("anh.jpg", PNG, "application/octet-stream"), "png", id="png-misnamed"),
    ],
)
async def test_user_uploads_avatar_and_gets_url(
    client: AsyncClient,
    db_session: AsyncSession,
    storage_dir: Path,
    file: tuple[str, bytes, str],
    extension: str,
) -> None:
    user = await create_user(db_session)
    filename, data, content_type = file

    response = await upload_avatar(client, user, data, filename, content_type)

    assert response.status_code == 200
    avatar_url = response.json()["avatar_url"]
    assert avatar_url.startswith(f"{base_url()}/{AVATAR_KEY_PREFIX}/{user.id}/")
    assert avatar_url.endswith(f".{extension}")
    assert stored_path(storage_dir, avatar_url).read_bytes() == data
    assert user.avatar_key == avatar_url.removeprefix(f"{base_url()}/")


async def test_uploaded_avatar_is_served_at_returned_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    avatar_url = (await upload_avatar(client, user, PNG)).json()["avatar_url"]

    response = await client.get(urlsplit(avatar_url).path)

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


async def test_me_returns_avatar_url(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    without_avatar = await client.get(ME_URL, headers=auth_headers(user))
    avatar_url = (await upload_avatar(client, user, PNG)).json()["avatar_url"]

    response = await client.get(ME_URL, headers=auth_headers(user))

    assert without_avatar.json()["avatar_url"] is None
    assert response.json()["avatar_url"] == avatar_url


async def test_update_profile_keeps_avatar_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    avatar_url = (await upload_avatar(client, user, PNG)).json()["avatar_url"]

    response = await client.patch(ME_URL, json={"full_name": "Tên Mới"}, headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json()["avatar_url"] == avatar_url


async def test_new_avatar_replaces_and_deletes_old_file(
    client: AsyncClient, db_session: AsyncSession, storage_dir: Path
) -> None:
    user = await create_user(db_session)
    old_url = (await upload_avatar(client, user, PNG)).json()["avatar_url"]

    response = await upload_avatar(client, user, JPEG, "moi.jpg", "image/jpeg")

    new_url = response.json()["avatar_url"]
    assert new_url != old_url
    assert stored_path(storage_dir, new_url).read_bytes() == JPEG
    assert not stored_path(storage_dir, old_url).exists()


async def test_avatar_over_size_limit_is_rejected(
    client: AsyncClient, db_session: AsyncSession, storage_dir: Path
) -> None:
    user = await create_user(db_session)
    user_dir = storage_dir / AVATAR_KEY_PREFIX / str(user.id)

    response = await upload_avatar(client, user, PNG.ljust(AVATAR_MAX_BYTES + 1, b"\0"))

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "FILE_TOO_LARGE"
    assert error["details"] == {"field": "file", "max_bytes": AVATAR_MAX_BYTES}
    assert user.avatar_key is None
    assert not user_dir.exists()


async def test_avatar_at_size_limit_is_accepted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)

    response = await upload_avatar(client, user, PNG.ljust(AVATAR_MAX_BYTES, b"\0"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        pytest.param(b"GIF89a-anh-gif", "anh.gif", "image/gif", id="gif"),
        # Đặt đuôi .png, Content-Type image/png nhưng nội dung không phải ảnh.
        pytest.param(b"<svg onload=alert(1)>", "anh.png", "image/png", id="fake-png"),
        pytest.param(b"", "anh.png", "image/png", id="empty"),
    ],
)
async def test_avatar_that_is_not_jpeg_or_png_is_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    data: bytes,
    filename: str,
    content_type: str,
) -> None:
    user = await create_user(db_session)

    response = await upload_avatar(client, user, data, filename, content_type)

    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_FILE_TYPE"
    assert error["details"] == {"field": "file", "allowed_types": ["image/jpeg", "image/png"]}
    assert user.avatar_key is None


async def test_avatar_requires_file_field(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session)

    response = await client.put(
        AVATAR_URL, files={"anh": ("anh.png", PNG, "image/png")}, headers=auth_headers(user)
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.file"


async def test_avatar_requires_token(client: AsyncClient) -> None:
    response = await client.put(AVATAR_URL, files={"file": ("anh.png", PNG, "image/png")})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_missing_local_file_returns_json_404(client: AsyncClient) -> None:
    response = await client.get(f"/media/{AVATAR_KEY_PREFIX}/0/khong-co.png")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
