from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TOKEN_HASH_LENGTH, TOKEN_JTI_MAX_LENGTH, TOKEN_PURPOSE_MAX_LENGTH
from app.core.database import Base, BigIntPK, CreatedAtMixin

if TYPE_CHECKING:
    from app.modules.users.models import User


class UserTokenPurpose(StrEnum):
    SETUP_PASSWORD = "SETUP_PASSWORD"  # noqa: S105 (mục đích của token, không phải mật khẩu)


class RefreshToken(CreatedAtMixin, Base):
    """Phiên đăng nhập. Chỉ lưu jti của refresh token, không lưu token gốc."""

    __tablename__ = "refresh_tokens"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(String(TOKEN_JTI_MAX_LENGTH), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="refresh_tokens", lazy="raise")


class UserToken(CreatedAtMixin, Base):
    """Token dùng một lần gửi qua email, ví dụ link đặt mật khẩu lần đầu. Chỉ lưu SHA-256."""

    __tablename__ = "user_tokens"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    # varchar + CHECK thay vì enum của PostgreSQL: thêm mục đích mới không phải ALTER TYPE.
    purpose: Mapped[UserTokenPurpose] = mapped_column(
        Enum(
            UserTokenPurpose,
            name="user_token_purpose",
            native_enum=False,
            create_constraint=True,
            length=TOKEN_PURPOSE_MAX_LENGTH,
        )
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="tokens", lazy="raise")
