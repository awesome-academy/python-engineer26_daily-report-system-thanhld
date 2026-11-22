from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Row,
    Select,
    and_,
    cast,
    exists,
    func,
    null,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Session, contains_eager, joinedload

from app.core.clock import local_date_sql, local_day_start
from app.core.pagination import DateRange, DateRangePageParams, paginate
from app.core.workdays import is_working_day_sql
from app.modules.departments.models import Department, DepartmentManager
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.reports.schemas import ManagerReportListParams, ReportExportParams, ReportSort
from app.modules.users.models import (
    User,
    UserRole,
    full_name_matches,
    is_employee_in,
    order_by_full_name,
)

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


def _report_readers() -> Select[User]:
    """Manager còn đọc được báo cáo của bộ phận mình: còn liên kết, đúng role, đăng nhập được.

    Manager chưa đặt mật khẩu, bị khóa hay bị xóa không đọc được báo cáo, nên không là
    người nhận. Xét lại role: liên kết manager là dữ liệu riêng, user đổi role thì liên kết vẫn
    còn. Dùng chung cho lúc tạo báo cáo (API), email S1 và thống kê tháng S3 (worker).
    """
    return (
        select(User)
        .join(DepartmentManager, DepartmentManager.user_id == User.id)
        .where(User.role == UserRole.MANAGER, User.can_log_in)
    )


def _eligible_recipients(department_id: int) -> Select[User]:
    """Người nhận được báo cáo của bộ phận `department_id`."""
    return _report_readers().where(DepartmentManager.department_id == department_id)


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

    async def list_daily_export_rows(
        self, department_ids: Select[int], params: ReportExportParams
    ) -> Sequence[tuple[Department, User, DailyReport | None]]:
        """Dòng của file export một ngày (M5) trong các bộ phận `department_ids`, một câu SQL.

        - Đã nộp: báo cáo ngày đó viết cho bộ phận (bộ phận lúc viết, index (department_id,
          report_date)), kể cả người viết đã bị khóa, xóa, đổi role như danh sách M3.
        - Chưa nộp: nhân viên hiện tại của bộ phận (như M4) đã có tài khoản trước khi hết ngày đó
          (giờ Việt Nam) mà không có báo cáo ngày đó ở bộ phận nào: người chuyển bộ phận sau khi nộp
          đã có dòng ở bộ phận cũ. Không lưu lịch sử thành viên nên ngày cũ cũng xét thành viên
          hiện tại.

        Sắp theo mã bộ phận rồi họ tên ngay trong SQL (`order_by_full_name`).
        """
        day = params.report_date
        submitted = select(
            DailyReport.department_id.label("department_id"),
            DailyReport.author_id.label("user_id"),
            DailyReport.id.label("report_id"),
        ).where(DailyReport.department_id.in_(department_ids), DailyReport.report_date == day)
        missing = select(User.department_id, User.id, cast(null(), BigInteger)).where(
            is_employee_in(department_ids),
            User.created_at < local_day_start(day + timedelta(days=1)),
            ~exists().where(DailyReport.author_id == User.id, DailyReport.report_date == day),
        )
        rows = union_all(submitted, missing).subquery()
        statement = (
            select(Department, User, DailyReport)
            .select_from(rows)
            .join(Department, Department.id == rows.c.department_id)
            .join(User, User.id == rows.c.user_id)
            .outerjoin(DailyReport, DailyReport.id == rows.c.report_id)
            .order_by(Department.code, *order_by_full_name())
        )
        # Vẫn giữ điều kiện phạm vi ở trên: bộ lọc đã kiểm tra ở dependency, câu truy vấn không
        # trông vào bước đó.
        if params.department_id is not None:
            statement = statement.where(Department.id == params.department_id)
        return (await self.session.execute(statement)).all()

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


class MonthlySummaryRepository:
    """Truy vấn cho email thống kê tháng S3 bằng session đồng bộ (Celery worker)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_employee_stats(
        self, first: date, last: date
    ) -> Sequence[Row[int | None, int, str, bool, date, int]]:
        """Số ngày làm việc đã nộp báo cáo từ `first` đến `last` của từng nhân viên, một câu SQL.

        Dòng (bộ phận, nhân viên, họ tên, còn hoạt động, ngày bắt đầu tính, số ngày đã nộp), GROUP
        BY bộ phận, nhân viên:
        - Nhân viên hiện tại (như M4, M5) của bộ phận chưa xóa, có tài khoản trước khi hết `last`.
          Không lưu lịch sử thành viên, nên người chuyển bộ phận giữa tháng tính ở bộ phận mới.
        - Tính từ ngày tạo tài khoản (giờ Việt Nam) nếu tạo giữa tháng: ngày trước đó chưa phải
          nộp (API cũng không nhận báo cáo cho ngày trước khi có tài khoản).
        - Chỉ đếm báo cáo vào ngày làm việc, ở mọi bộ phận (mỗi người một báo cáo một ngày), dùng
          unique (author_id, report_date). Số ngày đã nộp không vượt số ngày phải nộp.

        Sắp theo bộ phận rồi họ tên ngay trong SQL (`order_by_full_name`).
        """
        starts_on = local_date_sql(User.created_at)
        active_departments = select(Department.id).where(Department.deleted_at.is_(None))
        statement = (
            select(
                User.department_id,
                User.id,
                User.full_name,
                User.is_active,
                func.greatest(starts_on, first),
                func.count(DailyReport.id),
            )
            .outerjoin(
                DailyReport,
                and_(
                    DailyReport.author_id == User.id,
                    DailyReport.report_date.between(first, last),
                    DailyReport.report_date >= starts_on,
                    is_working_day_sql(DailyReport.report_date),
                ),
            )
            .where(
                is_employee_in(active_departments),
                User.created_at < local_day_start(last + timedelta(days=1)),
            )
            .group_by(User.department_id, User.id)
            .order_by(User.department_id, *order_by_full_name())
        )
        return self.session.execute(statement).all()

    def list_recipients(self) -> Sequence[Row[int, str, int, str, str]]:
        """Manager nhận thống kê của từng bộ phận chưa xóa, cùng điều kiện người nhận báo cáo.

        Dòng (bộ phận, tên bộ phận, manager, email, họ tên), sắp theo bộ phận rồi manager.
        """
        statement = (
            _report_readers()
            .join(Department, Department.id == DepartmentManager.department_id)
            .where(Department.deleted_at.is_(None))
            .with_only_columns(
                DepartmentManager.department_id,
                Department.name,
                User.id,
                User.email,
                User.full_name,
            )
            .order_by(DepartmentManager.department_id, User.id)
        )
        return self.session.execute(statement).all()
