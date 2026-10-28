from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import JWT_SECRET_MIN_LENGTH, LOGIN_MAX_FAILED_ATTEMPTS
from app.core.security import decode_access_token, verify_password
from app.modules.users.models import User, UserRole
from tests.factories import DEFAULT_PASSWORD, auth_headers, create_user
from tests.helpers import bearer, login, login_tokens, make_token, refresh

ME_URL = "/api/v1/me"
PASSWORD_URL = "/api/v1/me/password"
NEW_PASSWORD = "MatKhauMoi#2026"
WRONG_PASSWORD = "SaiMatKhau@1"


async def test_me_returns_current_user_without_sensitive_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, email="an@example.com", full_name="Nguyễn Văn An")

    response = await client.get(ME_URL, headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["email"], body["full_name"], body["role"]) == (
        user.id,
        "an@example.com",
        "Nguyễn Văn An",
        "USER",
    )
    assert "password_hash" not in body
    assert "token_version" not in body


async def test_token_from_login_can_call_me(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")
    login = await client.post(
        "/api/v1/auth/login", data={"username": "an@example.com", "password": DEFAULT_PASSWORD}
    )

    response = await client.get(
        ME_URL, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "an@example.com"


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "build_token",
    [
        pytest.param(lambda _: "khong-phai-jwt", id="malformed"),
        pytest.param(
            lambda uid: make_token(uid, exp=datetime.now(UTC) - timedelta(seconds=1)), id="expired"
        ),
        pytest.param(
            lambda uid: make_token(uid, secret="x" * JWT_SECRET_MIN_LENGTH), id="wrong-signature"
        ),
        pytest.param(lambda uid: make_token(uid, type="refresh"), id="wrong-type"),
        pytest.param(lambda uid: make_token(uid + 1000), id="unknown-user"),
    ],
)
async def test_me_rejects_invalid_token(
    client: AsyncClient, db_session: AsyncSession, build_token: Callable[[int], str]
) -> None:
    user = await create_user(db_session)

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {build_token(user.id)}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_me_rejects_token_issued_before_token_version_changed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    headers = auth_headers(user)
    user.token_version += 1
    await db_session.flush()

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 401


async def test_me_rejects_token_of_deactivated_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    headers = auth_headers(user)
    user.is_active = False
    await db_session.flush()

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 401


async def test_update_me_changes_only_sent_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, full_name="Nguyễn Văn An")

    response = await client.patch(
        ME_URL,
        json={"phone": " 0912345678 ", "date_of_birth": "1995-03-15"},
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["full_name"], body["phone"], body["date_of_birth"]) == (
        "Nguyễn Văn An",
        "0912345678",
        "1995-03-15",
    )
    await db_session.refresh(user)
    assert (user.phone, user.date_of_birth) == ("0912345678", date(1995, 3, 15))


async def test_update_me_clears_optional_fields_with_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)
    user.phone = "0912345678"
    user.date_of_birth = date(1995, 3, 15)
    await db_session.flush()

    response = await client.patch(
        ME_URL,
        json={"full_name": "  Trần Thị Bình ", "phone": None, "date_of_birth": None},
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    stored = await db_session.execute(
        select(User.full_name, User.phone, User.date_of_birth).where(User.id == user.id)
    )
    assert tuple(stored.one()) == ("Trần Thị Bình", None, None)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "moi@example.com"}, "body.email"),
        ({"role": UserRole.ADMIN.value}, "body.role"),
        ({"full_name": "Tên mới", "role": UserRole.ADMIN.value}, "body.role"),
    ],
    ids=["email", "role", "role-with-valid-field"],
)
async def test_update_me_cannot_change_email_or_role(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, Any], field: str
) -> None:
    user = await create_user(db_session, email="an@example.com", full_name="Nguyễn Văn An")

    response = await client.patch(ME_URL, json=body, headers=auth_headers(user))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field
    await db_session.refresh(user)
    assert (user.email, user.role, user.full_name) == (
        "an@example.com",
        UserRole.USER,
        "Nguyễn Văn An",
    )


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"full_name": None}, "body.full_name"),
        ({"full_name": "   "}, "body.full_name"),
        ({"phone": "09-1234-5678"}, "body.phone"),
        (
            {"date_of_birth": (datetime.now(UTC) + timedelta(days=2)).date().isoformat()},
            "body.date_of_birth",
        ),
    ],
    ids=["name-null", "name-blank", "phone-format", "birthday-in-future"],
)
async def test_update_me_rejects_invalid_values(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, Any], field: str
) -> None:
    user = await create_user(db_session)

    response = await client.patch(ME_URL, json=body, headers=auth_headers(user))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == field


@pytest.mark.parametrize(
    ("method", "url"), [("PATCH", ME_URL), ("PUT", PASSWORD_URL)], ids=["profile", "password"]
)
async def test_profile_endpoints_require_token(client: AsyncClient, method: str, url: str) -> None:
    response = await client.request(
        method, url, json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def change_password(
    client: AsyncClient, access_token: str, current: str, new: str = NEW_PASSWORD
) -> Response:
    return await client.put(
        PASSWORD_URL,
        json={"current_password": current, "new_password": new},
        headers=bearer(access_token),
    )


async def test_change_password_replaces_password_and_returns_new_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    response = await change_password(client, tokens["access_token"], DEFAULT_PASSWORD)

    assert response.status_code == 200
    new_access = response.json()["access_token"]
    await db_session.refresh(user)
    assert user.token_version == 1
    assert decode_access_token(new_access).token_version == user.token_version
    assert user.password_hash is not None
    assert await verify_password(NEW_PASSWORD, user.password_hash)
    assert (await client.get(ME_URL, headers=bearer(new_access))).status_code == 200
    assert (await refresh(client, response.json()["refresh_token"])).status_code == 200
    assert (await login(client, "an@example.com", NEW_PASSWORD)).status_code == 200
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 401


async def test_change_password_ends_all_previous_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    current = await login_tokens(client, "an@example.com")
    other_device = await login_tokens(client, "an@example.com")

    await change_password(client, current["access_token"], DEFAULT_PASSWORD)

    for tokens in (current, other_device):
        assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 401
        assert (await refresh(client, tokens["refresh_token"])).status_code == 401


async def test_old_refresh_token_after_password_change_does_not_end_new_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Thiết bị khác tự refresh bằng token cũ không được bị coi là token bị lộ.
    await create_user(db_session, email="an@example.com")
    current = await login_tokens(client, "an@example.com")
    other_device = await login_tokens(client, "an@example.com")
    new_tokens = (await change_password(client, current["access_token"], DEFAULT_PASSWORD)).json()

    await refresh(client, other_device["refresh_token"])

    response = await client.get(ME_URL, headers=bearer(new_tokens["access_token"]))
    assert response.status_code == 200


async def test_change_password_rejects_wrong_current_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    response = await change_password(client, tokens["access_token"], WRONG_PASSWORD)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "CURRENT_PASSWORD_INCORRECT",
        "message": "Mật khẩu hiện tại không đúng.",
        "details": {"field": "current_password"},
    }
    await db_session.refresh(user)
    assert user.token_version == 0
    assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 200


async def test_change_password_locks_after_too_many_wrong_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")
    for _ in range(LOGIN_MAX_FAILED_ATTEMPTS):
        await change_password(client, tokens["access_token"], WRONG_PASSWORD)

    response = await change_password(client, tokens["access_token"], DEFAULT_PASSWORD)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    # Bộ đếm dùng chung với đăng nhập.
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 429


@pytest.mark.parametrize(
    ("new_password", "message"),
    [
        ("Ngan@1", "at least"),
        ("matkhau@123", "chữ hoa"),
        ("MATKHAU@123", "chữ thường"),
        ("Matkhau@abc", "chữ số"),
        ("Matkhau1234", "ký tự đặc biệt"),
        (DEFAULT_PASSWORD, "khác mật khẩu hiện tại"),
    ],
    ids=["too-short", "no-upper", "no-lower", "no-digit", "no-special", "same-as-current"],
)
async def test_change_password_rejects_weak_new_password(
    client: AsyncClient, db_session: AsyncSession, new_password: str, message: str
) -> None:
    user = await create_user(db_session)

    response = await client.put(
        PASSWORD_URL,
        json={"current_password": DEFAULT_PASSWORD, "new_password": new_password},
        headers=auth_headers(user),
    )

    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]
    assert detail["field"] == "body.new_password"
    assert message in detail["message"]
