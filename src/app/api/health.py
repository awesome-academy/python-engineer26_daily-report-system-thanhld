"""GET /health: kiểm tra kết nối PostgreSQL và Redis."""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, RedisClient
from app.core.constants import HEALTH_CHECK_TIMEOUT_SECONDS

CheckStatus = Literal["ok", "error"]

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["Hệ thống"])


class HealthResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


async def _check_database(session: AsyncSession) -> CheckStatus:
    try:
        async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        logger.exception("health_check_failed", component="database")
        return "error"
    return "ok"


async def _check_redis(redis: Redis) -> CheckStatus:
    try:
        async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
            await redis.ping()
    except (RedisError, OSError):
        logger.exception("health_check_failed", component="redis")
        return "error"
    return "ok"


@router.get(
    "/health",
    summary="Kiểm tra trạng thái hệ thống",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(session: DbSession, redis: RedisClient, response: Response) -> HealthResponse:
    checks = {
        "database": await _check_database(session),
        "redis": await _check_redis(redis),
    }
    healthy = all(result == "ok" for result in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "error", checks=checks)
