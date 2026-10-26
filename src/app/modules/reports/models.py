from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK, TimestampMixin

if TYPE_CHECKING:
    from app.modules.departments.models import Department
    from app.modules.users.models import User

# Mỗi nhân viên một báo cáo mỗi ngày. Cột đầu author_id cũng phục vụ tra báo cáo theo user.
REPORT_AUTHOR_DATE_UNIQUE = "uq_daily_reports_author_date"


class DailyReport(TimestampMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint("author_id", "report_date", name=REPORT_AUTHOR_DATE_UNIQUE),
        # Màn hình manager, export và thống kê tháng lọc theo bộ phận và ngày.
        Index("ix_daily_reports_department_date", "department_id", "report_date"),
    )

    id: Mapped[BigIntPK]
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    # Bộ phận tại thời điểm viết: nhân viên chuyển bộ phận không làm sai thống kê cũ.
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="RESTRICT")
    )
    report_date: Mapped[date] = mapped_column(Date)
    planned_work: Mapped[str] = mapped_column(Text)
    actual_work: Mapped[str] = mapped_column(Text)
    incomplete_reason: Mapped[str | None] = mapped_column(Text)
    next_day_plan: Mapped[str] = mapped_column(Text)

    author: Mapped["User"] = relationship(back_populates="reports", lazy="raise")
    department: Mapped["Department"] = relationship(back_populates="reports", lazy="raise")
    recipients: Mapped[list["ReportRecipient"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class ReportRecipient(Base):
    __tablename__ = "report_recipients"

    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_reports.id", ondelete="CASCADE"), primary_key=True
    )
    recipient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    # Ghi khi đã gửi email thông báo (S1).
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    report: Mapped["DailyReport"] = relationship(back_populates="recipients", lazy="raise")
    recipient: Mapped["User"] = relationship(lazy="raise")
