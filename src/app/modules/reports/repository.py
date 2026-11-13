from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Session, contains_eager, joinedload

from app.core.pagination import DateRange, DateRangePageParams, paginate
from app.modules.departments.models import DepartmentManager
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.reports.schemas import ManagerReportListParams, ReportSort
from app.modules.users.models import User, UserRole, full_name_matches, order_by_full_name

# Mỗi thứ tự sắp đều xét cả ngày và người viết (order_by_full_name có id): một người một báo cáo
# mỗi ngày, nên không có hai báo cáo cùng vị trí, thứ tự cố định giữa các trang.
_SORTS: dict[ReportSort, tuple[ColumnElement[Any] | InstrumentedAttribute[Any], ...]] = {
    ReportSort.REPORT_DATE_DESC: (DailyReport.report_date.desc(), *order_by_full_name()),
    ReportSort.REPORT_DATE: (DailyReport.report_date, *order_by_full_name()),
    ReportSort.AUTHOR_NAME: (*order_by_full_name(), DailyReport.report_date.desc()),
    ReportSort.AUTHOR_NAME_DESC: (
        *(column.desc() for column in order_by_full_name()),
        DailyReport.report_date.desc(),
    ),
}


def _in_date_range(statement: Select[Any], date_range: DateRange) -> Select[Any]:
    if date_range.date_from is not None:
        statement = statement.where(DailyReport.report_date >= date_range.date_from)
    if date_range.date_to is not None:
        statement = statement.where(DailyReport.report_date <= date_range.date_to)
    return statement


def _eligible_recipients(department_id: int) -> Select[User]:
    """Manager của bộ phận còn nhận được báo cáo: còn liên kết, đúng role, đăng nhập được để đọc.

    Manager chưa đặt mật khẩu, bị khóa hay bị xóa không đọc được báo cáo, nên không là
    người nhận. Xét lại role: liên kết manager là dữ liệu riêng, user đổi role thì liên kết vẫn
    còn. Dùng chung cho lúc tạo báo cáo (API) và lúc gửi email S1 (worker).
    """
    return (
        select(User)
        .join(DepartmentManager, DepartmentManager.user_id == User.id)
        .where(
            DepartmentManager.department_id == department_id,
            User.role == UserRole.MANAGER,
            User.can_log_in,
        )
    )


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists_for_date(self, author_id: int, report_date: date) -> bool:
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        DailyReport.author_id == author_id, DailyReport.report_date == report_date
                    )
                )
            )
        )

    async def list_recipients(self, department_id: int) -> Sequence[User]:
        statement = _eligible_recipients(department_id).order_by(*order_by_full_name())
        return (await self.session.scalars(statement)).all()

    async def search_by_author(
        self, author_id: int, params: DateRangePageParams
    ) -> tuple[Sequence[DailyReport], int]:
        # Unique (author_id, report_date) là index phục vụ luôn điều kiện và thứ tự sắp này.
        statement = (
            select(DailyReport)
            .where(DailyReport.author_id == author_id)
            .order_by(DailyReport.report_date.desc())
        )
        return await paginate(self.session, _in_date_range(statement, params), params)

    async def search_in_departments(
        self, department_ids: Select[int], params: ManagerReportListParams
    ) -> tuple[Sequence[DailyReport], int]:
        """Báo cáo viết cho các bộ phận `department_ids` (bộ phận lúc viết), kèm người viết.

        Điều kiện bộ phận và ngày dùng index (department_id, report_date). Người viết lấy cùng câu
        (JOIN) vì cần để tìm, sắp theo tên.
        """
        statement = (
            select(DailyReport)
            .join(DailyReport.author)
            .options(contains_eager(DailyReport.author))
            .where(DailyReport.department_id.in_(department_ids))
            .order_by(*_SORTS[params.sort])
        )
        if params.department_id is not None:
            statement = statement.where(DailyReport.department_id == params.department_id)
        if params.keyword:
            statement = statement.where(full_name_matches(params.keyword))
        return await paginate(self.session, _in_date_range(statement, params), params)

    async def get_by_author(self, report_id: int, author_id: int) -> DailyReport | None:
        """Báo cáo kèm bộ phận; báo cáo của người khác coi như không tồn tại."""
        return await self.session.scalar(
            select(DailyReport)
            .where(DailyReport.id == report_id, DailyReport.author_id == author_id)
            .options(joinedload(DailyReport.department))
        )

    async def get_in_departments(
        self, report_id: int, department_ids: Select[int]
    ) -> DailyReport | None:
        """Báo cáo kèm bộ phận, người viết; ngoài `department_ids` coi như không tồn tại."""
        return await self.session.scalar(
            select(DailyReport)
            .where(DailyReport.id == report_id, DailyReport.department_id.in_(department_ids))
            .options(joinedload(DailyReport.department), joinedload(DailyReport.author))
        )

    async def get_report_recipients(self, report_id: int) -> Sequence[User]:
        """Người nhận của báo cáo, kể cả người đã bị khóa, bị xóa sau khi nhận (lịch sử).

        Truy vấn riêng thay cho selectinload để sắp theo tên ngay trong SQL.
        """
        statement = (
            select(User)
            .join(ReportRecipient, ReportRecipient.recipient_id == User.id)
            .where(ReportRecipient.report_id == report_id)
            .order_by(*order_by_full_name())
        )
        return (await self.session.scalars(statement)).all()

    def add(self, report: DailyReport) -> None:
        self.session.add(report)


class ReportNotificationRepository:
    """Truy vấn cho email S1 bằng session đồng bộ (Celery worker)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_with_author(self, report_id: int) -> DailyReport | None:
        return self.session.scalar(
            select(DailyReport)
            .where(DailyReport.id == report_id)
            .options(joinedload(DailyReport.author), joinedload(DailyReport.department))
        )

    def eligible_recipient_ids(self, department_id: int) -> set[int]:
        """Id manager còn nhận được báo cáo của bộ phận, cùng điều kiện với lúc tạo báo cáo."""
        statement = _eligible_recipients(department_id).with_only_columns(User.id)
        return set(self.session.scalars(statement))

    def list_unnotified_recipients(self, report_id: int) -> Sequence[ReportRecipient]:
        """Người nhận chưa được gửi email, kèm tài khoản; task chạy lại thì bỏ qua người đã gửi."""
        statement = (
            select(ReportRecipient)
            .where(ReportRecipient.report_id == report_id, ReportRecipient.notified_at.is_(None))
            .options(joinedload(ReportRecipient.recipient))
            .order_by(ReportRecipient.recipient_id)
        )
        return self.session.scalars(statement).all()
