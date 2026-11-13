from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.auth.models import RefreshToken, UserToken, UserTokenPurpose


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, token: RefreshToken) -> RefreshToken:
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_by_jti_for_update(self, jti: str) -> RefreshToken | None:
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
        )

    async def revoke_session(self, *, user_id: int, session_id: str, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.session_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_all(self, *, user_id: int, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )


class UserTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hash(
        self, token_hash: str, purpose: UserTokenPurpose, *, for_update: bool = False
    ) -> UserToken | None:
        statement = select(UserToken).where(
            UserToken.token_hash == token_hash, UserToken.purpose == purpose
        )
        if for_update:
            # populate_existing: token đã đọc trước khi chờ khóa được nạp lại bản mới nhất.
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)


class UserTokenSyncRepository:
    """Ghi bảng user_tokens bằng session đồng bộ (Celery worker cấp link đặt mật khẩu)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: UserToken) -> None:
        self.session.add(token)
        self.session.flush()

    def delete_for_user(self, user_id: int, purpose: UserTokenPurpose) -> None:
        self.session.execute(
            delete(UserToken).where(UserToken.user_id == user_id, UserToken.purpose == purpose)
        )
