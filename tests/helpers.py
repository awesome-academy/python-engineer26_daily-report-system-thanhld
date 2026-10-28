"""Helper dùng chung cho test."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from httpx import AsyncClient, Response
from typer.testing import CliRunner, Result

from app.cli import cli
from app.core.config import get_settings
from tests.factories import DEFAULT_PASSWORD

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"

runner = CliRunner()


async def invoke(*args: str) -> Result:
    # Lệnh CLI tự chạy asyncio.run(), nên phải chạy ở thread khác event loop của test.
    def run() -> Result:
        return runner.invoke(cli, list(args))

    return await asyncio.to_thread(run)


def make_token(user_id: int, **overrides: Any) -> str:
    """Ghép JWT bằng tay để thử token hết hạn, sai chữ ký, sai loại. Mặc định là access token."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": "USER",
        "ver": 0,
        "jti": "test",
        "sid": "test",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    settings = get_settings()
    secret = overrides.pop("secret", settings.jwt_secret_key)
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm=settings.jwt_algorithm)


async def login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post(LOGIN_URL, data={"username": email, "password": password})


async def login_tokens(client: AsyncClient, email: str) -> dict[str, str]:
    response = await login(client, email, DEFAULT_PASSWORD)
    assert response.status_code == 200
    tokens: dict[str, str] = response.json()
    return tokens


async def refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post(REFRESH_URL, json={"refresh_token": refresh_token})


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
