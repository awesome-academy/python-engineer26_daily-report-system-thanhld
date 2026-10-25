from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_dummy_password, verify_password
from app.modules.auth.exceptions import InvalidCredentialsError
from app.modules.auth.schemas import TokenResponse
from app.modules.users.repository import UserRepository


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.users.get_by_email(email)
        if user is None or user.password_hash is None:
            await verify_dummy_password(password)
            raise InvalidCredentialsError

        # Luôn kiểm tra mật khẩu trước, để tài khoản bị khóa không trả lời nhanh hơn.
        password_ok = await verify_password(password, user.password_hash)
        if not password_ok or not user.can_log_in:
            raise InvalidCredentialsError

        user.last_login_at = datetime.now(UTC)
        await self.session.commit()

        token = create_access_token(
            user_id=user.id, role=user.role, token_version=user.token_version
        )
        return TokenResponse(access_token=token.token, expires_in=token.expires_in)
