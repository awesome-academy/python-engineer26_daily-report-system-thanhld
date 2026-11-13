"""POST /auth/setup-password: đặt mật khẩu lần đầu bằng token trong link email (S2)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import ONE_TIME_TOKEN_MAX_LENGTH
from app.core.security import create_one_time_token, verify_password
from app.modules.auth.models import UserToken
from app.modules.users.models import User
from tests.factories import DEFAULT_PASSWORD, create_setup_token, create_user
from tests.helpers import login

API = get_settings().api_v1_prefix
SETUP_URL = f"{API}/auth/setup-password"
NEW_PASSWORD = "MatKhauMoi@2026"


@pytest.fixture
async def new_user(db_session: AsyncSession) -> User:
    """Tài khoản admin vừa tạo: chưa có mật khẩu."""
    return await create_user(db_session, email="binh@example.com", password=None)


async def setup_password(client: AsyncClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return await client.post(SETUP_URL, json={"token": token, "password": password})


def assert_token_invalid(response: Any) -> None:
    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "SETUP_TOKEN_INVALID",
        "message": (
            "Link đặt mật khẩu không hợp lệ, đã được dùng hoặc đã hết hạn. "
            "Liên hệ quản trị viên để nhận link mới."
        ),
        "details": {"field": "token"},
    }


async def reload(session: AsyncSession, model: type[Any], row_id: int) -> Any:
    return await session.scalar(
        select(model).where(model.id == row_id).execution_options(populate_existing=True)
    )


async def test_new_user_sets_password_then_logs_in(
    client: AsyncClient, db_session: AsyncSession, new_user: User
) -> None:
    token = await create_setup_token(db_session, new_user)

    response = await setup_password(client, token)

    assert response.status_code == 204
    assert response.content == b""
    login_response = await login(client, "binh@example.com", NEW_PASSWORD)
    assert login_response.status_code == 200
    [stored] = (await db_session.scalars(select(UserToken))).all()
    await db_session.refresh(stored)
    assert stored.used_at is not None


async def test_link_cannot_be_used_twice(
    client: AsyncClient, db_session: AsyncSession, new_user: User
) -> None:
    token = await create_setup_token(db_session, new_user)
    await setup_password(client, token)

    response = await setup_password(client, token, password="KhacHoan@2026")

    assert_token_invalid(response)
    # Lần dùng thứ hai không ghi đè mật khẩu vừa đặt.
    user = await reload(db_session, User, new_user.id)
    assert await verify_password(NEW_PASSWORD, user.password_hash)


async def test_expired_link_is_rejected(
    client: AsyncClient, db_session: AsyncSession, new_user: User
) -> None:
    token = await create_setup_token(
        db_session, new_user, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )

    response = await setup_password(client, token)

    assert_token_invalid(response)
    assert (await reload(db_session, User, new_user.id)).password_hash is None


async def test_link_shortly_before_expiry_still_works(
    client: AsyncClient, db_session: AsyncSession, new_user: User
) -> None:
    token = await create_setup_token(
        db_session, new_user, expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )

    response = await setup_password(client, token)

    assert response.status_code == 204


async def test_unknown_token_is_rejected(client: AsyncClient, new_user: User) -> None:
    response = await setup_password(client, create_one_time_token().token)

    assert_token_invalid(response)


@pytest.mark.parametrize(
    "fields",
    [{"is_active": False}, {"deleted": True}, {"password": DEFAULT_PASSWORD}],
    ids=["inactive", "deleted", "password-already-set"],
)
async def test_link_of_account_that_cannot_set_password_is_rejected(
    client: AsyncClient, db_session: AsyncSession, fields: dict[str, Any]
) -> None:
    # Bị khóa (gửi nhầm người thì admin khóa lại), đã xóa, hoặc đã có mật khẩu: link không còn
    # dùng được, kể cả còn hạn. Link chỉ cho đặt lần đầu, không thành đường đổi mật khẩu.
    user = await create_user(db_session, **({"password": None} | fields))
    token = await create_setup_token(db_session, user)

    response = await setup_password(client, token)

    assert_token_invalid(response)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"password": NEW_PASSWORD}, "body.token"),
        ({"token": "abc"}, "body.password"),
        ({"token": "abc", "password": "matkhauyeu"}, "body.password"),
        ({"token": "abc+/=", "password": NEW_PASSWORD}, "body.token"),
        ({"token": "abc\x00", "password": NEW_PASSWORD}, "body.token"),
        ({"token": "a" * (ONE_TIME_TOKEN_MAX_LENGTH + 1), "password": NEW_PASSWORD}, "body.token"),
        ({"token": "abc", "password": NEW_PASSWORD, "email": "x@example.com"}, "body.email"),
    ],
    ids=[
        "missing-token",
        "missing-password",
        "weak-password",
        "token-not-base64url",
        "token-with-nul",
        "token-too-long",
        "unknown-field",
    ],
)
async def test_setup_password_rejects_invalid_body(
    client: AsyncClient, body: dict[str, str], field: str
) -> None:
    response = await client.post(SETUP_URL, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in [detail["field"] for detail in response.json()["error"]["details"]]


async def test_setup_password_documents_errors_in_openapi(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    operation = response.json()["paths"][SETUP_URL]["post"]
    error_schema = {"$ref": "#/components/schemas/ErrorResponse"}
    for status_code in ("400", "422"):
        content = operation["responses"][status_code]["content"]["application/json"]
        assert content["schema"] == error_schema
