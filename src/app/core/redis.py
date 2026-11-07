"""Client Redis dùng chung cho API: blacklist token, đếm số lần đăng nhập sai."""

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.constants import REDIS_TIMEOUT_SECONDS

redis_client = Redis.from_url(
    get_settings().redis_url,
    decode_responses=True,
    socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    socket_timeout=REDIS_TIMEOUT_SECONDS,
)


async def get_redis() -> Redis:
    return redis_client
