from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, Enum, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, BigIntPK, SoftDeleteMixin, TimestampMixin


class UserRole(StrEnum):
    USER = "USER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class User(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    id: Mapped[BigIntPK]
    email: Mapped[str] = mapped_column(String(255))
    # Null đến khi user đặt mật khẩu qua link trong email (S2).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.USER, server_default=UserRole.USER.value
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Tăng khi đổi mật khẩu, khóa hoặc xóa user: mọi access token cũ hết hiệu lực ngay.
    token_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def can_log_in(self) -> bool:
        return self.is_active and self.deleted_at is None and self.password_hash is not None


# Email không trùng (không phân biệt hoa thường) trong số user chưa bị xóa mềm.
Index(
    "uq_users_email_active",
    func.lower(User.email),
    unique=True,
    postgresql_where=User.deleted_at.is_(None),
)
# Tìm tên không dấu: "nguyen van a" khớp "Nguyễn Văn A". Hàm immutable_unaccent ở migration 0001.
Index(
    "ix_users_full_name_search",
    func.immutable_unaccent(func.lower(User.full_name)).label("full_name_search"),
    postgresql_using="gin",
    postgresql_ops={"full_name_search": "gin_trgm_ops"},
)
