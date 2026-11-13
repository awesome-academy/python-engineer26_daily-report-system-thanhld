import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import (
    REFRESH_TOKEN_REUSE_GRACE_SECONDS,
    SETUP_PASSWORD_PATH,
    SETUP_PASSWORD_TOKEN_EXPIRE_HOURS,
)
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    AccessTokenClaims,
    create_access_token,
    create_one_time_token,
    create_refresh_token,
    decode_refresh_token,
    hash_one_time_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.modules.auth.blacklist import blacklist_session
from app.modules.auth.exceptions import (
    CurrentPasswordIncorrectError,
    InvalidCredentialsError,
    SetupTokenInvalidError,
)
from app.modules.auth.login_attempts import LoginAttempts
from app.modules.auth.models import RefreshToken, UserToken, UserTokenPurpose
from app.modules.auth.repository import (
    RefreshTokenRepository,
    UserTokenRepository,
    UserTokenSyncRepository,
)
from app.modules.auth.schemas import PasswordSetup, TokenResponse
from app.modules.users.models import User
from app.modules.users.repository import UserRepository, UserSyncRepository
from app.modules.users.schemas import PasswordChange

logger = structlog.get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self.session = session
        self.redis = redis
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.user_tokens = UserTokenRepository(session)
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

    async def change_password(
        self, user: User, session_id: str, data: PasswordChange
    ) -> TokenResponse:
        """Đổi mật khẩu, mọi phiên khác hết hiệu lực; phiên hiện tại nhận cặp token mới.

        Cặp token mới giữ `session_id` của phiên hiện tại, nên đăng xuất sau đó vẫn thu hồi đúng
        phiên này.

        Tăng token_version là đủ chặn mọi access token và refresh token cũ. Không đánh dấu thu hồi
        refresh token: thiết bị khác gửi token đã thu hồi sẽ bị coi là token bị lộ, và phiên vừa
        đổi mật khẩu cũng bị đăng xuất theo.
        """
        # Dùng chung bộ đếm với đăng nhập: người cầm access token bị lộ không dò được mật khẩu.
        await self.login_attempts.register(user.email)
        token_version = user.token_version
        # Khóa dòng rồi kiểm tra lại phiên: trong lúc chờ khóa, request khác có thể đã đổi mật khẩu,
        # khóa tài khoản hoặc thu hồi mọi phiên. Khi đó phiên này đã hết hiệu lực, trả 401.
        locked = await self.users.get_by_id_for_update(user.id)
        if locked is None or not locked.can_log_in or locked.token_version != token_version:
            await self.session.rollback()
            raise UnauthorizedError
        if locked.password_hash is None or not await verify_password(
            data.current_password, locked.password_hash
        ):
            await self.session.rollback()
            raise CurrentPasswordIncorrectError

        await self.login_attempts.reset(user.email)
        locked.password_hash = await hash_password(data.new_password)
        locked.token_version += 1
        return await self._issue_tokens(locked, session_id=session_id)

    async def setup_password(self, data: PasswordSetup) -> None:
        """Đặt mật khẩu lần đầu bằng token trong link email (S2). Token chỉ dùng được một lần."""
        token_hash = hash_one_time_token(data.token)
        purpose = UserTokenPurpose.SETUP_PASSWORD
        now = datetime.now(UTC)
        # Kiểm tra trước khi khóa và trước khi băm: token sai không tốn Argon2, khóa giữ ngắn.
        token = await self.user_tokens.get_by_hash(token_hash, purpose)
        if token is None or not token.is_usable(now):
            raise SetupTokenInvalidError
        password_hash = await hash_password(data.password)

        # Khóa user rồi mới khóa token, cùng thứ tự với worker cấp link mới (AccountSetupService),
        # để hai bên không chờ khóa của nhau (deadlock). Kiểm tra lại sau khi có khóa: request
        # khác cùng token có thể vừa dùng xong, worker có thể vừa thay link mới.
        user = await self.users.get_by_id_for_update(token.user_id)
        locked_token = await self.user_tokens.get_by_hash(token_hash, purpose, for_update=True)
        if (
            user is None
            or locked_token is None
            or not locked_token.is_usable(now)
            or not user.is_active
            or user.password_hash is not None
        ):
            await self.session.rollback()
            raise SetupTokenInvalidError

        user.password_hash = password_hash
        locked_token.used_at = now
        await self.session.commit()

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


@dataclass(frozen=True, slots=True)
class AccountSetupLink:
    email: str
    full_name: str
    url: str


def setup_password_url(token: str) -> str:
    base = str(get_settings().frontend_url).rstrip("/")
    return f"{base}{SETUP_PASSWORD_PATH}?{urlencode({'token': token})}"


class AccountSetupService:
    """Cấp link đặt mật khẩu lần đầu (S2). Chạy trong Celery worker, session đồng bộ.

    Token sinh ở worker, không ở API: token gốc không nằm trong message trên Redis, chỉ có trong
    email; DB chỉ lưu SHA-256.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserSyncRepository(session)
        self.tokens = UserTokenSyncRepository(session)

    def issue_link(self, user_id: int, now: datetime) -> AccountSetupLink | None:
        """Tạo link mới và xóa link cũ, nên chỉ link trong email gửi sau cùng còn dùng được.

        Trả None khi user không còn cần đặt mật khẩu: đã bị xóa, bị khóa hoặc đã có mật khẩu
        (task chạy lại sau khi user đặt xong).
        """
        # Khóa user: cấp link không chạy xen với lệnh đặt mật khẩu (cùng khóa user trước).
        user = self.users.get_by_id_for_update(user_id)
        if user is None or not user.is_active or user.password_hash is not None:
            self.session.rollback()
            return None

        purpose = UserTokenPurpose.SETUP_PASSWORD
        self.tokens.delete_for_user(user.id, purpose)
        token = create_one_time_token()
        self.tokens.add(
            UserToken(
                user_id=user.id,
                token_hash=token.token_hash,
                purpose=purpose,
                expires_at=now + timedelta(hours=SETUP_PASSWORD_TOKEN_EXPIRE_HOURS),
            )
        )
        self.session.commit()
        return AccountSetupLink(
            email=user.email, full_name=user.full_name, url=setup_password_url(token.token)
        )
