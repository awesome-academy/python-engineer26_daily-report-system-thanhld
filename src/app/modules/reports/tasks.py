"""Celery task của báo cáo: email S1 cho người nhận."""

from typing import Any

import structlog
from celery import Task

from app.core.config import get_settings
from app.core.constants import TASK_MAX_RETRIES
from app.core.database import sync_session
from app.modules.notifications.mailer import SmtpMailer
from app.modules.notifications.service import EmailService
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
