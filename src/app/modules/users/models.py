from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    PASSWORD_HASH_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    STORAGE_KEY_MAX_LENGTH,
)
from app.core.database import Base, BigIntPK, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.modules.auth.models import RefreshToken, UserToken
    from app.modules.departments.models import Department
    from app.modules.reports.models import DailyReport


class UserRole(StrEnum):
    USER = "USER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class User(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    id: Mapped[BigIntPK]
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    # Null đến khi user đặt mật khẩu qua link trong email (S2).
    password_hash: Mapped[str | None] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH))
    full_name: Mapped[str] = mapped_column(String(FULL_NAME_MAX_LENGTH))
    phone: Mapped[str | None] = mapped_column(String(PHONE_MAX_LENGTH))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.USER, server_default=UserRole.USER.value
    )
    # Một nhân viên thuộc một bộ phận (Q1). Bộ phận bị xóa cứng thì về null.
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    avatar_key: Mapped[str | None] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Tăng khi đổi mật khẩu, khóa hoặc xóa user: mọi access token cũ hết hiệu lực ngay.
    token_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # lazy="raise": cấm tự load quan hệ khi truy cập (gây N+1, và lỗi với session async).
    # Cần dữ liệu quan hệ thì load rõ ràng bằng selectinload/joinedload trong repository.
    department: Mapped["Department | None"] = relationship(back_populates="members", lazy="raise")
    # Chỉ đọc, xem Department.managers.
    managed_departments: Mapped[list["Department"]] = relationship(
        secondary="department_managers",
        back_populates="managers",
        viewonly=True,
        lazy="raise",
    )
    # RESTRICT ở DB giữ lịch sử báo cáo; ORM không tự sửa hay xóa báo cáo khi xóa user.
    reports: Mapped[list["DailyReport"]] = relationship(
        back_populates="author", passive_deletes="all", lazy="raise"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    tokens: Mapped[list["UserToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    @property
    def can_log_in(self) -> bool:
        return self.is_active and self.deleted_at is None and self.password_hash is not None


# Email không trùng (không phân biệt hoa thường) trong số user chưa bị xóa mềm.
USER_EMAIL_UNIQUE_INDEX = "uq_users_email_active"
Index(
    USER_EMAIL_UNIQUE_INDEX,
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
