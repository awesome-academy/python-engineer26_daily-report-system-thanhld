"""Blacklist phiên đăng nhập trên Redis.

Access token đã đăng xuất vẫn đúng chữ ký và còn hạn, nên chỉ từ chối được nhờ danh sách này.
Blacklist theo mã phiên (claim sid) chứ không theo từng token, để cả access token cấp trước lần
refresh gần nhất cũng bị từ chối.
"""

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.constants import REDIS_REVOKED_SESSION_PREFIX


def _key(session_id: str) -> str:
    return f"{REDIS_REVOKED_SESSION_PREFIX}{session_id}"


async def blacklist_session(redis: Redis, session_id: str) -> None:
    # Access token cấp muộn nhất của phiên hết hạn sau tối đa chừng này giây, sau đó
    # decode_access_token tự từ chối nên không cần giữ key nữa.
    ttl = get_settings().access_token_expire_minutes * 60
    await redis.set(_key(session_id), 1, ex=ttl)


async def is_session_blacklisted(redis: Redis, session_id: str) -> bool:
    return bool(await redis.exists(_key(session_id)))
