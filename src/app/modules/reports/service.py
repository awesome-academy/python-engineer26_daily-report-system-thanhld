from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import local_date
from app.core.constants import REPORT_BACKDATE_DAYS
from app.core.database import commit_unique
from app.modules.reports.exceptions import (
    InvalidRecipientError,
    NoRecipientError,
    ReportAlreadyExistsError,
    ReportDateOutOfRangeError,
)
from app.modules.reports.models import REPORT_AUTHOR_DATE_UNIQUE, DailyReport, ReportRecipient
from app.modules.reports.repository import ReportRepository
from app.modules.reports.schemas import ReportCreate
from app.modules.users.models import User


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = ReportRepository(session)

    async def list_recipients(self, author: User) -> Sequence[User]:
        if author.department_id is None:
            return []
        return await self.reports.list_recipients(author.department_id)

    async def create_report(self, author: User, data: ReportCreate, *, today: date) -> DailyReport:
        """Lưu báo cáo cùng người nhận trong một lần commit: lỗi ở bước nào thì không lưu gì.

        `today` tính theo múi giờ nghiệp vụ, do router truyền vào để test cố định được ngày.
        """
        # Không báo cáo cho ngày trước khi có tài khoản: ngày đó không thuộc kỳ làm việc của user,
        # tính vào thống kê tháng sẽ sai.
        min_date = max(today - timedelta(days=REPORT_BACKDATE_DAYS), local_date(author.created_at))
        if not min_date <= data.report_date <= today:
            raise ReportDateOutOfRangeError(min_date, today)
        if await self.reports.exists_for_date(author.id, data.report_date):
            raise ReportAlreadyExistsError(data.report_date)
        recipients = await self._resolve_recipients(author, data.recipient_ids)

        report = DailyReport(
            author_id=author.id,
            # Có người nhận nghĩa là user đang thuộc một bộ phận (_resolve_recipients).
            department_id=author.department_id,
            **data.model_dump(exclude={"recipient_ids"}),
        )
        report.recipients = [ReportRecipient(recipient=user) for user in recipients]
        self.reports.add(report)
        await commit_unique(
            self.session, REPORT_AUTHOR_DATE_UNIQUE, ReportAlreadyExistsError(data.report_date)
        )
        return report

    async def _resolve_recipients(
        self, author: User, recipient_ids: list[int] | None
    ) -> Sequence[User]:
        allowed = await self.list_recipients(author)
        if not allowed:
            raise NoRecipientError
        # Không chọn thì gửi cho mọi manager của bộ phận (Q4).
        if recipient_ids is None:
            return allowed
        by_id = {user.id: user for user in allowed}
        invalid_ids = [user_id for user_id in recipient_ids if user_id not in by_id]
        if invalid_ids:
            raise InvalidRecipientError(invalid_ids)
        return [by_id[user_id] for user_id in recipient_ids]
