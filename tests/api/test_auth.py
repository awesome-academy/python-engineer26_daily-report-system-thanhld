from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import (
    JWT_MAX_LENGTH,
    JWT_SECRET_MIN_LENGTH,
    LOGIN_ATTEMPT_WINDOW_MINUTES,
    LOGIN_MAX_FAILED_ATTEMPTS,
    REDIS_REVOKED_SESSION_PREFIX,
    REFRESH_TOKEN_REUSE_GRACE_SECONDS,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    decode_refresh_token,
)
from app.modules.auth.models import RefreshToken
from tests.factories import DEFAULT_PASSWORD, create_user
from tests.helpers import (
    LOGIN_URL,
    REFRESH_URL,
    bearer,
    login,
    login_tokens,
    make_token,
    refresh,
)

LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/me"
WRONG_PASSWORD = "SaiMatKhau@1"


async def fail_login(client: AsyncClient, email: str, times: int) -> None:
    for _ in range(times):
        assert (await login(client, email, WRONG_PASSWORD)).status_code == 401


async def get_refresh_token_row(session: AsyncSession, refresh_token: str) -> RefreshToken:
    jti = decode_refresh_token(refresh_token).jti
    row = await session.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    assert row is not None
    await session.refresh(row)
    return row


async def test_login_returns_bearer_token(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, email="an@example.com")

    response = await login(client, "an@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert decode_access_token(body["access_token"]).user_id == user.id


async def test_login_ignores_email_case(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")

    response = await login(client, "An@Example.COM", DEFAULT_PASSWORD)

    assert response.status_code == 200


async def test_login_records_last_login_time(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, email="an@example.com")

    await login(client, "an@example.com", DEFAULT_PASSWORD)

    await db_session.refresh(user)
    assert user.last_login_at is not None


@pytest.mark.parametrize(
    "case", ["wrong_password", "unknown_email", "inactive", "deleted", "password_not_set"]
)
async def test_login_rejects_invalid_credentials_with_same_error(
    client: AsyncClient, db_session: AsyncSession, case: str
) -> None:
    await create_user(
        db_session,
        email="an@example.com",
        is_active=case != "inactive",
        deleted=case == "deleted",
        password=None if case == "password_not_set" else DEFAULT_PASSWORD,
    )
    email = "khong-ton-tai@example.com" if case == "unknown_email" else "an@example.com"
    password = "SaiMatKhau@1" if case == "wrong_password" else DEFAULT_PASSWORD

    response = await login(client, email, password)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Email hoặc mật khẩu không đúng.",
        "details": None,
    }


async def test_login_requires_username_and_password(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, data={})

    assert response.status_code == 422
    fields = {detail["field"] for detail in response.json()["error"]["details"]}
    assert fields == {"body.username", "body.password"}


async def test_swagger_uses_login_endpoint_for_authorize_button(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    flows = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]
    assert flows["password"]["tokenUrl"] == LOGIN_URL


async def test_login_returns_refresh_token_bound_to_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session, email="an@example.com")

    tokens = await login_tokens(client, "an@example.com")

    row = await get_refresh_token_row(db_session, tokens["refresh_token"])
    assert row.user_id == user.id
    assert row.revoked_at is None
    assert decode_access_token(tokens["access_token"]).session_id == row.session_id


async def test_refresh_returns_new_tokens_and_revokes_old_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    assert new_tokens["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert (await client.get(ME_URL, headers=bearer(new_tokens["access_token"]))).status_code == 200
    old_row = await get_refresh_token_row(db_session, tokens["refresh_token"])
    new_row = await get_refresh_token_row(db_session, new_tokens["refresh_token"])
    assert old_row.revoked_at is not None
    assert new_row.session_id == old_row.session_id
    assert decode_access_token(new_tokens["access_token"]).session_id == old_row.session_id


async def test_reused_refresh_token_revokes_all_sessions_of_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    stolen = await login_tokens(client, "an@example.com")
    other_device = await login_tokens(client, "an@example.com")
    rotated = (await refresh(client, stolen["refresh_token"])).json()
    row = await get_refresh_token_row(db_session, stolen["refresh_token"])
    assert row.revoked_at is not None
    row.revoked_at -= timedelta(seconds=REFRESH_TOKEN_REUSE_GRACE_SECONDS)
    await db_session.flush()

    response = await refresh(client, stolen["refresh_token"])

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    for tokens in (rotated, other_device):
        assert (await refresh(client, tokens["refresh_token"])).status_code == 401
        assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 401


async def test_refresh_retried_right_after_rotation_keeps_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Client gửi lại request refresh (timeout, hai tab cùng refresh): chỉ từ chối request sau.
    await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")
    other_device = await login_tokens(client, "an@example.com")
    rotated = (await refresh(client, tokens["refresh_token"])).json()

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 401
    assert (await client.get(ME_URL, headers=bearer(rotated["access_token"]))).status_code == 200
    assert (await refresh(client, rotated["refresh_token"])).status_code == 200
    assert (await refresh(client, other_device["refresh_token"])).status_code == 200


@pytest.mark.parametrize(
    "build_token",
    [
        pytest.param(lambda _: "khong-phai-jwt", id="malformed"),
        pytest.param(lambda uid: make_token(uid, type="refresh", jti="khong-co"), id="unknown-jti"),
        pytest.param(
            lambda uid: make_token(
                uid, type="refresh", exp=datetime.now(UTC) - timedelta(seconds=1)
            ),
            id="expired",
        ),
        pytest.param(
            lambda uid: make_token(uid, type="refresh", secret="x" * JWT_SECRET_MIN_LENGTH),
            id="wrong-signature",
        ),
        pytest.param(
            lambda uid: (
                create_access_token(user_id=uid, role="USER", token_version=0, session_id="s").token
            ),
            id="access-token",
        ),
    ],
)
async def test_refresh_rejects_invalid_token(
    client: AsyncClient, db_session: AsyncSession, build_token: Callable[[int], str]
) -> None:
    user = await create_user(db_session)

    response = await refresh(client, build_token(user.id))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_refresh_rejects_token_of_another_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    other = await create_user(db_session)
    tokens = await login_tokens(client, "an@example.com")
    jti = decode_refresh_token(tokens["refresh_token"]).jti

    response = await refresh(client, make_token(other.id, type="refresh", jti=jti))

    assert response.status_code == 401


@pytest.mark.parametrize("change", ["deactivated", "deleted", "token_version"])
async def test_refresh_rejects_user_who_can_no_longer_log_in(
    client: AsyncClient, db_session: AsyncSession, change: str
) -> None:
    user = await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")
    if change == "deactivated":
        user.is_active = False
    elif change == "deleted":
        user.deleted_at = datetime.now(UTC)
    else:
        user.token_version += 1
    await db_session.flush()

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing"),
        pytest.param({"refresh_token": "x" * (JWT_MAX_LENGTH + 1)}, id="too-long"),
    ],
)
async def test_refresh_validates_body(client: AsyncClient, body: dict[str, str]) -> None:
    response = await client.post(REFRESH_URL, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.refresh_token"


async def test_logout_rejects_access_and_refresh_token_immediately(
    client: AsyncClient, db_session: AsyncSession, redis: Redis
) -> None:
    await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    response = await client.post(LOGOUT_URL, headers=bearer(tokens["access_token"]))

    assert response.status_code == 204
    me = await client.get(ME_URL, headers=bearer(tokens["access_token"]))
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "UNAUTHORIZED"
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401
    session_id = decode_access_token(tokens["access_token"]).session_id
    ttl = await redis.ttl(f"{REDIS_REVOKED_SESSION_PREFIX}{session_id}")
    assert 0 < ttl <= get_settings().access_token_expire_minutes * 60


async def test_logout_keeps_other_sessions(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")
    current = await login_tokens(client, "an@example.com")
    other_device = await login_tokens(client, "an@example.com")

    await client.post(LOGOUT_URL, headers=bearer(current["access_token"]))

    assert (
        await client.get(ME_URL, headers=bearer(other_device["access_token"]))
    ).status_code == 200
    assert (await refresh(client, other_device["refresh_token"])).status_code == 200


async def test_logout_twice_with_same_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")
    await client.post(LOGOUT_URL, headers=bearer(tokens["access_token"]))

    response = await client.post(LOGOUT_URL, headers=bearer(tokens["access_token"]))

    assert response.status_code == 401


async def test_logout_requires_token(client: AsyncClient) -> None:
    response = await client.post(LOGOUT_URL)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_access_token_from_refresh_can_log_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    tokens = (
        await refresh(client, (await login_tokens(client, "an@example.com"))["refresh_token"])
    ).json()

    response = await client.post(LOGOUT_URL, headers=bearer(tokens["access_token"]))

    assert response.status_code == 204
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


async def test_logout_with_older_access_token_ends_whole_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    first = await login_tokens(client, "an@example.com")
    rotated = (await refresh(client, first["refresh_token"])).json()

    response = await client.post(LOGOUT_URL, headers=bearer(first["access_token"]))

    assert response.status_code == 204
    assert (await client.get(ME_URL, headers=bearer(rotated["access_token"]))).status_code == 401
    assert (await refresh(client, rotated["refresh_token"])).status_code == 401


async def test_logout_rejects_every_access_token_of_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    first = await login_tokens(client, "an@example.com")
    rotated = (await refresh(client, first["refresh_token"])).json()

    await client.post(LOGOUT_URL, headers=bearer(rotated["access_token"]))

    assert (await client.get(ME_URL, headers=bearer(first["access_token"]))).status_code == 401


@pytest.mark.parametrize("account", ["existing", "unknown"])
async def test_login_is_locked_after_too_many_failed_attempts(
    client: AsyncClient, db_session: AsyncSession, account: str
) -> None:
    if account == "existing":
        await create_user(db_session, email="an@example.com")
    await fail_login(client, "an@example.com", LOGIN_MAX_FAILED_ATTEMPTS)

    response = await login(client, "an@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    retry_after = int(response.headers["Retry-After"])
    assert 0 < retry_after <= LOGIN_ATTEMPT_WINDOW_MINUTES * 60


async def test_login_lock_ignores_email_case(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")
    await fail_login(client, "AN@example.com", LOGIN_MAX_FAILED_ATTEMPTS)

    response = await login(client, "an@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 429


async def test_login_lock_is_per_email(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session, email="binh@example.com")
    await fail_login(client, "an@example.com", LOGIN_MAX_FAILED_ATTEMPTS)

    response = await login(client, "binh@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 200


async def test_successful_login_resets_failed_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="an@example.com")
    await fail_login(client, "an@example.com", LOGIN_MAX_FAILED_ATTEMPTS - 1)
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 200
    await fail_login(client, "an@example.com", LOGIN_MAX_FAILED_ATTEMPTS - 1)

    response = await login(client, "an@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 200
