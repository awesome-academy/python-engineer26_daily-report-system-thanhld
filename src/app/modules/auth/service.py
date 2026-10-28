import uuid
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import REFRESH_TOKEN_REUSE_GRACE_SECONDS
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    AccessTokenClaims,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_dummy_password,
    verify_password,
)
from app.modules.auth.blacklist import blacklist_session
from app.modules.auth.exceptions import InvalidCredentialsError
from app.modules.auth.login_attempts import LoginAttempts
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import TokenResponse
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

logger = structlog.get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self.session = session
        self.redis = redis
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.login_attempts = LoginAttempts(redis)

    async def login(self, email: str, password: str) -> TokenResponse:
        await self.login_attempts.register(email)

        user = await self.users.get_by_email(email)
        if user is None or user.password_hash is None:
            await verify_dummy_password(password)
            raise InvalidCredentialsError

        # Luôn kiểm tra mật khẩu trước, để tài khoản bị khóa không trả lời nhanh hơn.
        password_ok = await verify_password(password, user.password_hash)
        if not password_ok or not user.can_log_in:
            raise InvalidCredentialsError

        await self.login_attempts.reset(email)
        user.last_login_at = datetime.now(UTC)
        return await self._issue_tokens(user, session_id=uuid.uuid4().hex)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """Xoay vòng: refresh token chỉ dùng được một lần, mỗi lần đổi lấy cặp token mới."""
        claims = decode_refresh_token(refresh_token)
        # Khóa dòng: hai request cùng một token chạy song song thì request sau thấy token đã
        # bị thu hồi, không lấy được cặp token thứ hai.
        stored = await self.refresh_tokens.get_by_jti_for_update(claims.jti)
        if stored is None or stored.user_id != claims.user_id:
            await self.session.rollback()
            raise UnauthorizedError

        now = datetime.now(UTC)
        if stored.revoked_at is not None:
            if now - stored.revoked_at < timedelta(seconds=REFRESH_TOKEN_REUSE_GRACE_SECONDS):
                await self.session.rollback()
            else:
                await self._revoke_all_sessions(claims.user_id, now)
            raise UnauthorizedError

        user = await self.users.get_by_id(claims.user_id)
        if user is None or not user.can_log_in or user.token_version != claims.token_version:
            await self.session.rollback()
            raise UnauthorizedError

        stored.revoked_at = now
        return await self._issue_tokens(user, session_id=stored.session_id)

    async def logout(self, claims: AccessTokenClaims) -> None:
        """Thu hồi cả phiên: mọi refresh token và access token cấp trong phiên.

        Đăng xuất bằng access token nào của phiên (kể cả token cấp trước lần refresh gần nhất)
        cũng có hiệu lực như nhau.
        """
        await self.refresh_tokens.revoke_session(
            user_id=claims.user_id, session_id=claims.session_id, revoked_at=datetime.now(UTC)
        )
        await self.session.commit()
        await blacklist_session(self.redis, claims.session_id)

    async def _revoke_all_sessions(self, user_id: int, now: datetime) -> None:
        """Refresh token đã thu hồi quá khoảng ân hạn bị gửi lại: token có thể đã lộ.

        Không biết bên nào là chủ tài khoản, nên thu hồi mọi phiên của user, và tăng
        token_version để cả access token đang dùng cũng hết hiệu lực ngay.
        """
        await self.refresh_tokens.revoke_all(user_id=user_id, revoked_at=now)
        user = await self.users.get_by_id(user_id)
        if user is not None:
            user.token_version += 1
        await self.session.commit()
        logger.warning("refresh_token_reused", user_id=user_id)

    async def _issue_tokens(self, user: User, *, session_id: str) -> TokenResponse:
        refresh = create_refresh_token(user_id=user.id, token_version=user.token_version)
        await self.refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                jti=refresh.jti,
                session_id=session_id,
                expires_at=refresh.expires_at,
            )
        )
        await self.session.commit()

        access = create_access_token(
            user_id=user.id,
            role=user.role,
            token_version=user.token_version,
            session_id=session_id,
        )
        return TokenResponse(
            access_token=access.token, refresh_token=refresh.token, expires_in=access.expires_in
        )
