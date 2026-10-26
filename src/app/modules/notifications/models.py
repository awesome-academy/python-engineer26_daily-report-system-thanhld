from enum import StrEnum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    EMAIL_DEDUP_KEY_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    EMAIL_STATUS_MAX_LENGTH,
    EMAIL_TEMPLATE_MAX_LENGTH,
)
from app.core.database import Base, BigIntPK, CreatedAtMixin


class EmailStatus(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"


class EmailLog(CreatedAtMixin, Base):
    """Nhật ký email đã gửi. Không có khóa ngoại để ghi được cả địa chỉ chưa có tài khoản."""

    __tablename__ = "email_logs"

    id: Mapped[BigIntPK]
    to_email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    template: Mapped[str] = mapped_column(String(EMAIL_TEMPLATE_MAX_LENGTH))
    # Chống gửi trùng khi job chạy lại, ví dụ "monthly:2026-10:dept:3:user:7" (S3).
    dedup_key: Mapped[str | None] = mapped_column(String(EMAIL_DEDUP_KEY_MAX_LENGTH), unique=True)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(
            EmailStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=EMAIL_STATUS_MAX_LENGTH,
        )
    )
    error: Mapped[str | None] = mapped_column(Text)
