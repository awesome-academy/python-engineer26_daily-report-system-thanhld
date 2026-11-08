"""Email S1: báo cho người nhận khi nhân viên tạo báo cáo (chạy trong Celery worker)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.core.constants import EMAIL_DATE_FORMAT
from app.modules.notifications.mailer import RETRYABLE_ERRORS
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.service import EmailService
from app.modules.reports.models import DailyReport
from app.modules.reports.repository import ReportNotificationRepository
from app.modules.users.models import User

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FailedEmail:
    to_email: str
    error: Exception


class ReportNotifier:
    def __init__(self, session: Session, emails: EmailService) -> None:
        self.session = session
        self.emails = emails
        self.reports = ReportNotificationRepository(session)

    def notify(self, report_id: int) -> list[FailedEmail]:
        """Gửi email cho từng người nhận chưa có `notified_at`, trả về các email gửi lỗi.

        Mỗi người nhận gửi xong thì commit log SENT cùng `notified_at`: task chạy lại (thử lại
        sau lỗi, worker giao lại task) chỉ gửi cho người chưa nhận. Một người gửi lỗi không chặn
        những người còn lại.
        """
        report = self.reports.get_with_author(report_id)
        if report is None:
            # Báo cáo chưa có API xóa; gặp trường hợp này là dữ liệu bị xóa tay sau khi đẩy task.
            logger.warning("report_notification_skipped", report_id=report_id, reason="not_found")
            return []
        failures: list[FailedEmail] = []
        for item in self.reports.list_unnotified_recipients(report_id):
            recipient = item.recipient
            # Người nhận bị khóa, bị xóa sau khi báo cáo được tạo thì không còn đọc được báo cáo.
            if not recipient.can_log_in:
                logger.warning(
                    "report_notification_skipped",
                    report_id=report_id,
                    recipient_id=recipient.id,
                    reason="recipient_unavailable",
                )
                continue
            try:
                self.emails.deliver(
                    recipient.email, EmailTemplate.REPORT_CREATED, _context(report, recipient)
                )
            except RETRYABLE_ERRORS as exc:
                failures.append(FailedEmail(recipient.email, exc))
                continue
            item.notified_at = datetime.now(UTC)
            self.session.commit()
        return failures

    def record_failures(self, failures: list[FailedEmail]) -> None:
        for failure in failures:
            self.emails.record_failure(
                failure.to_email, EmailTemplate.REPORT_CREATED, failure.error
            )


def _context(report: DailyReport, recipient: User) -> dict[str, Any]:
    return {
        "recipient_name": recipient.full_name,
        "author_name": report.author.full_name,
        "department_name": report.department.name,
        "report_date": report.report_date.strftime(EMAIL_DATE_FORMAT),
        "planned_work": report.planned_work,
        "actual_work": report.actual_work,
        "incomplete_reason": report.incomplete_reason,
        "next_day_plan": report.next_day_plan,
    }
