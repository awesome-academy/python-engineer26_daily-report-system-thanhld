from collections.abc import Sequence
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.departments.models import DepartmentManager
from app.modules.reports.models import DailyReport
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

    def add(self, report: DailyReport) -> None:
        self.session.add(report)
