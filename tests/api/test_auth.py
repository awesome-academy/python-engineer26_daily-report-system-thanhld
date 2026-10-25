import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from tests.factories import DEFAULT_PASSWORD, create_user

LOGIN_URL = "/api/v1/auth/login"


async def login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post(LOGIN_URL, data={"username": email, "password": password})


async def test_login_returns_bearer_token(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session, email="an@example.com")

    response = await login(client, "an@example.com", DEFAULT_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
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
