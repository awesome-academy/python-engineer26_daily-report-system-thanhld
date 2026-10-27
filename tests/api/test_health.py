from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.core.database import get_db_session
from app.core.redis import get_redis


class BrokenRedis:
    async def ping(self) -> bool:
        raise RedisConnectionError("redis is down")


class BrokenSession:
    async def execute(self, *_: object) -> None:
        raise OperationalError("SELECT 1", {}, OSError("database is down"))


async def test_health_reports_ok_when_dependencies_are_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_health_returns_503_when_redis_is_down(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_redis] = BrokenRedis

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "checks": {"database": "ok", "redis": "error"}}


async def test_health_returns_503_when_database_is_down(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_db_session] = BrokenSession

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "error", "redis": "ok"}
