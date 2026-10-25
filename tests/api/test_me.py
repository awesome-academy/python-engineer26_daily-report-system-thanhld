from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from tests.factories import DEFAULT_PASSWORD, auth_headers, create_user

ME_URL = "/api/v1/me"


def make_token(user_id: int, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": "USER",
        "ver": 0,
        "jti": "test",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    secret = overrides.pop("secret", get_settings().jwt_secret_key)
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


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
        pytest.param(lambda uid: make_token(uid, secret="x" * 40), id="wrong-signature"),
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
