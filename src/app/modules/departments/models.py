from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEPARTMENT_CODE_MAX_LENGTH, DEPARTMENT_NAME_MAX_LENGTH
from app.core.database import Base, BigIntPK, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.modules.reports.models import DailyReport
    from app.modules.users.models import User


class Department(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "departments"

    id: Mapped[BigIntPK]
    code: Mapped[str] = mapped_column(String(DEPARTMENT_CODE_MAX_LENGTH))
    name: Mapped[str] = mapped_column(String(DEPARTMENT_NAME_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text)

    # passive_deletes: DB tự SET NULL / CASCADE / RESTRICT, ORM không load danh sách để xử lý.
    members: Mapped[list["User"]] = relationship(
        back_populates="department", passive_deletes=True, lazy="raise"
    )
    # Chỉ đọc: gán, bỏ manager bằng cách thêm, xóa DepartmentManager. Ghi qua cả hai đường trong
    # một session thì SQLAlchemy không biết hai bên là một dòng, dễ insert trùng khóa chính.
    managers: Mapped[list["User"]] = relationship(
        secondary="department_managers",
        back_populates="managed_departments",
        viewonly=True,
        lazy="raise",
    )
    reports: Mapped[list["DailyReport"]] = relationship(
        back_populates="department", passive_deletes="all", lazy="raise"
    )


class DepartmentManager(Base):
    """Bảng liên kết manager và bộ phận: một bộ phận nhiều manager, một manager nhiều bộ phận."""

    __tablename__ = "department_managers"

    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True
    )
    # Index riêng cho user_id: cột thứ hai của khóa chính ghép không dùng được để tra theo user.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Mã bộ phận không trùng trong số bộ phận chưa bị xóa mềm.
DEPARTMENT_CODE_UNIQUE_INDEX = "uq_departments_code_active"
Index(
    DEPARTMENT_CODE_UNIQUE_INDEX,
    Department.code,
    unique=True,
    postgresql_where=Department.deleted_at.is_(None),
)
