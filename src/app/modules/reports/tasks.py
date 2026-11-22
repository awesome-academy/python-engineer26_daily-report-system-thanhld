"""Celery task của báo cáo: email S1 cho người nhận, email thống kê tháng S3 cho manager."""

from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import MONTH_FORMAT, MONTHLY_SUMMARY_TASK, TASK_MAX_RETRIES
from app.core.database import sync_session
from app.modules.notifications.mailer import SmtpMailer
from app.modules.notifications.service import EmailService
from app.modules.reports.monthly_summary import MonthlySummarySender, resolve_month
from app.modules.reports.notifications import ReportNotifier
from app.worker import celery_app, retry_or_give_up

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="reports.send_report_notification", max_retries=TASK_MAX_RETRIES)
def send_report_notification(self: Task[Any, Any], report_id: int) -> None:
    """Gửi email báo cáo mới cho người nhận; ai gửi lỗi thì thử lại cả task.

    Lần thử lại chỉ gửi cho người chưa nhận (`notified_at` rỗng). Hết lượt thì ghi email_logs
    FAILED cho từng người còn lỗi, không ném lỗi.
    """
    log = logger.bind(task_id=self.request.id, report_id=report_id)
    with sync_session() as session:
        notifier = ReportNotifier(session, EmailService(session, SmtpMailer(get_settings())))
        failures = notifier.notify(report_id)
        if not failures:
            log.info("report_notification_done")
            return
        retry_or_give_up(self, failures[0].error)
        log.error("report_notification_failed", failed=len(failures), error=repr(failures[0].error))
        notifier.record_failures(failures)


@celery_app.task(bind=True, name=MONTHLY_SUMMARY_TASK, max_retries=TASK_MAX_RETRIES)
def send_monthly_summaries(self: Task[Any, Any], month: str | None = None) -> None:
    """Email thống kê báo cáo tháng `month` ("2026-10") cho manager từng bộ phận.

    Celery Beat gọi không tham số lúc 08:00 ngày 1: thống kê tháng trước theo giờ Việt Nam. Email
    đã gửi (email_logs.dedup_key) thì bỏ qua, nên chạy lại, giao lại hay thử lại chỉ gửi email còn
    thiếu. Thử lại truyền đúng tháng đã tính. Hết lượt thì ghi FAILED cho email còn lỗi.
    """
    first = resolve_month(month, local_today())
    summary_month = first.strftime(MONTH_FORMAT)
    log = logger.bind(
        task_id=self.request.id, month=summary_month, attempt=self.request.retries + 1
    )
    with sync_session() as session:
        sender = MonthlySummarySender(session, EmailService(session, SmtpMailer(get_settings())))
        result = sender.send(first, datetime.now(UTC))
        if not result.failures:
            log.info("monthly_summary_done", sent=result.sent, already_sent=result.already_sent)
            return
        retry_or_give_up(self, result.failures[0].error, args=(summary_month,))
        log.error(
            "monthly_summary_failed",
            failed=len(result.failures),
            error=repr(result.failures[0].error),
        )
        sender.record_failures(result.failures)
