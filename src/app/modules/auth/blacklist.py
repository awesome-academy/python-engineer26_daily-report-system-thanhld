"""Blacklist access token trên Redis.

Access token đã đăng xuất vẫn đúng chữ ký và còn hạn, nên chỉ từ chối được nhờ danh sách này.
"""

import math
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.constants import REDIS_ACCESS_TOKEN_BLACKLIST_PREFIX
from app.core.security import AccessTokenClaims


def _key(jti: str) -> str:
    return f"{REDIS_ACCESS_TOKEN_BLACKLIST_PREFIX}{jti}"


async def revoke_access_token(redis: Redis, claims: AccessTokenClaims) -> None:
    # Chỉ cần giữ đến khi token hết hạn, sau đó decode_access_token tự từ chối.
    ttl = math.ceil((claims.expires_at - datetime.now(UTC)).total_seconds())
    if ttl > 0:
        await redis.set(_key(claims.jti), 1, ex=ttl)


async def is_access_token_revoked(redis: Redis, jti: str) -> bool:
    return bool(await redis.exists(_key(jti)))
