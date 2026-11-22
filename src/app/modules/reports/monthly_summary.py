"""Email S3: thống kê báo cáo tháng của từng bộ phận cho manager (chạy trong Celery worker)."""

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.core.clock import local_datetime
from app.core.constants import (
    EMAIL_DATETIME_FORMAT,
    EMAIL_MONTH_FORMAT,
    MONTH_FORMAT,
    MONTH_PATTERN,
    MONTHLY_SUMMARY_DEDUP_KEY,
)
from app.core.workdays import count_working_days
from app.modules.notifications.mailer import RETRYABLE_ERRORS
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.service import EmailService
from app.modules.reports.notifications import FailedEmail
from app.modules.reports.repository import MonthlySummaryRepository

logger = structlog.get_logger(__name__)


def previous_month(today: date) -> date:
    """Ngày đầu của tháng trước tháng chứa `today`."""
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def resolve_month(month: str | None, today: date) -> date:
    """Ngày đầu tháng cần thống kê: `month` dạng "2026-10", bỏ trống là tháng trước `today`.

    Tháng chưa kết thúc (tháng này, tháng sau) báo `ValueError`: số ngày phải nộp sẽ tính cả ngày
    chưa tới, và email đã gửi giữ `dedup_key` nên lần chạy đúng lịch của tháng đó bị bỏ qua.
    """
    last_finished = previous_month(today)
    if month is None:
        return last_finished
    if not re.fullmatch(MONTH_PATTERN, month):
        raise ValueError(f"Tháng {month!r} không đúng dạng YYYY-MM, ví dụ 2026-10")
    # Đã đúng mẫu nên strptime không lỗi. Chỉ lấy phần ngày, không cần múi giờ.
    first = datetime.strptime(month, MONTH_FORMAT).date()  # noqa: DTZ007
    if first > last_finished:
        raise ValueError(f"Tháng {month} chưa kết thúc, chỉ thống kê được tháng đã qua")
    return first


def month_end(first: date) -> date:
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def percent(part: int, whole: int) -> str:
    """Tỉ lệ phần trăm làm tròn xuống: chỉ nộp đủ mới hiện 100%. Tính bằng số nguyên cho đúng."""
    return f"{part * 100 // whole}%"


@dataclass(frozen=True, slots=True)
class EmployeeSummary:
    """Một dòng của bảng thống kê trong email."""

    full_name: str
    is_active: bool
    submitted_days: int
    working_days: int

    @property
    def missing_days(self) -> int:
        return self.working_days - self.submitted_days

    @property
    def rate(self) -> str:
        return percent(self.submitted_days, self.working_days)


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: int
    email: str
    full_name: str


@dataclass(slots=True)
class DepartmentRecipients:
    name: str
    managers: list[Recipient] = field(default_factory=list)


@dataclass(slots=True)
class MonthlySummaryResult:
    sent: int = 0
    # Đã gửi ở lần chạy trước (dedup_key đã có): Beat chạy lại, task được giao lại hay thử lại.
    already_sent: int = 0
    failures: list[FailedEmail] = field(default_factory=list)


class MonthlySummarySender:
    def __init__(self, session: Session, emails: EmailService) -> None:
        self.emails = emails
        self.summaries = MonthlySummaryRepository(session)

    def send(self, first: date, computed_at: datetime) -> MonthlySummaryResult:
        """Gửi thống kê tháng bắt đầu từ `first` cho từng manager của từng bộ phận.

        Mỗi (tháng, bộ phận, manager) một email, gửi xong commit log SENT kèm `dedup_key`: task
        chạy lại chỉ gửi email còn thiếu. Một email gửi lỗi không chặn những email còn lại. Bộ
        phận không có nhân viên phải nộp báo cáo thì không gửi. Email ghi `computed_at` là thời
        điểm tính số liệu: báo cáo bù nộp sau đó (Q6) không có trong thống kê.
        """
        month = first.strftime(MONTH_FORMAT)
        log = logger.bind(month=month)
        last = month_end(first)
        employees = self._employee_summaries(first, last)
        recipients = self._recipients()
        result = MonthlySummaryResult()
        for department_id, rows in employees.items():
            department = recipients.get(department_id)
            if department is None:
                # Có nhân viên mà không có manager nào nhận được: admin chưa gán, hay manager bị
                # khóa, chưa đặt mật khẩu. Không ai nhận thì ghi lại để admin biết.
                log.warning(
                    "monthly_summary_skipped", department_id=department_id, reason="no_recipient"
                )
                continue
            context = _context(first, last, computed_at, department.name, rows)
            for manager in department.managers:
                key = MONTHLY_SUMMARY_DEDUP_KEY.format(
                    month=month, department_id=department_id, user_id=manager.user_id
                )
                try:
                    sent = self.emails.send_once(
                        manager.email,
                        EmailTemplate.MONTHLY_SUMMARY,
                        {**context, "recipient_name": manager.full_name},
                        key,
                    )
                except RETRYABLE_ERRORS as exc:
                    result.failures.append(FailedEmail(manager.email, exc))
                    continue
                if sent:
                    result.sent += 1
                else:
                    result.already_sent += 1
        return result

    def record_failures(self, failures: list[FailedEmail]) -> None:
        for failure in failures:
            self.emails.record_failure(
                failure.to_email, EmailTemplate.MONTHLY_SUMMARY, failure.error
            )

    def _employee_summaries(self, first: date, last: date) -> dict[int, list[EmployeeSummary]]:
        """Dòng thống kê theo bộ phận, giữ thứ tự họ tên của SQL.

        Bỏ người không có ngày phải nộp (tạo tài khoản vào ngày nghỉ cuối tháng).
        """
        employees: dict[int, list[EmployeeSummary]] = defaultdict(list)
        stats = self.summaries.list_employee_stats(first, last)
        for department_id, _, full_name, is_active, starts_on, submitted_days in stats:
            working_days = count_working_days(starts_on, last)
            if department_id is None or working_days == 0:
                continue
            employees[department_id].append(
                EmployeeSummary(full_name, is_active, submitted_days, working_days)
            )
        return employees

    def _recipients(self) -> dict[int, DepartmentRecipients]:
        recipients: dict[int, DepartmentRecipients] = {}
        for department_id, name, user_id, email, full_name in self.summaries.list_recipients():
            department = recipients.setdefault(department_id, DepartmentRecipients(name))
            department.managers.append(Recipient(user_id, email, full_name))
        return recipients


def _context(
    first: date,
    last: date,
    computed_at: datetime,
    department_name: str,
    employees: list[EmployeeSummary],
) -> dict[str, Any]:
    submitted = sum(row.submitted_days for row in employees)
    expected = sum(row.working_days for row in employees)
    return {
        "department_name": department_name,
        "month": first.strftime(EMAIL_MONTH_FORMAT),
        "computed_at": local_datetime(computed_at).strftime(EMAIL_DATETIME_FORMAT),
        "working_days": count_working_days(first, last),
        "employees": employees,
        "complete_count": sum(row.missing_days == 0 for row in employees),
        "department_rate": percent(submitted, expected),
    }
