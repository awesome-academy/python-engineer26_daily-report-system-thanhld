from collections.abc import Sequence
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.pagination import DateRangePageParams, paginate
from app.modules.departments.models import DepartmentManager
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole, order_by_full_name


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
        """Manager của bộ phận còn nhận được báo cáo: đúng role, đăng nhập được để đọc.

        Manager chưa đặt mật khẩu, bị khóa hay bị xóa không đọc được báo cáo, nên không là
        người nhận.

        Xét lại role: liên kết manager là dữ liệu riêng, user đổi role thì liên kết vẫn còn.
        """
        statement = (
            select(User)
            .join(DepartmentManager, DepartmentManager.user_id == User.id)
            .where(
                DepartmentManager.department_id == department_id,
                User.role == UserRole.MANAGER,
                User.can_log_in,
            )
            .order_by(*order_by_full_name())
        )
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
        if params.date_from is not None:
            statement = statement.where(DailyReport.report_date >= params.date_from)
        if params.date_to is not None:
            statement = statement.where(DailyReport.report_date <= params.date_to)
        return await paginate(self.session, statement, params)

    async def get_by_author(self, report_id: int, author_id: int) -> DailyReport | None:
        """Báo cáo kèm bộ phận; báo cáo của người khác coi như không tồn tại."""
        return await self.session.scalar(
            select(DailyReport)
            .where(DailyReport.id == report_id, DailyReport.author_id == author_id)
            .options(joinedload(DailyReport.department))
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
