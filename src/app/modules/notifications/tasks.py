"""Celery task gửi email."""

import smtplib
from typing import Any

import structlog
from celery import Task

from app.core.config import get_settings
from app.core.constants import EMAIL_MAX_RETRIES, EMAIL_RETRY_BACKOFF_SECONDS
from app.core.database import sync_session
from app.modules.notifications.mailer import SmtpMailer
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.service import EmailService
from app.worker import celery_app

logger = structlog.get_logger(__name__)

# Lỗi có thể hết khi thử lại: SMTP server tạm từ chối, mất kết nối, timeout (OSError).
RETRYABLE_ERRORS = (smtplib.SMTPException, OSError)


def retry_countdown(retries: int) -> int:
    """Số giây chờ trước lần thử lại thứ `retries + 1`: 30s, 60s, 120s."""
    return int(EMAIL_RETRY_BACKOFF_SECONDS * 2**retries)


@celery_app.task(bind=True, name="notifications.send_email", max_retries=EMAIL_MAX_RETRIES)
def send_email(self: Task[Any, Any], to_email: str, template: str, context: dict[str, Any]) -> None:
    """Gửi một email theo template; lỗi thì thử lại tối đa EMAIL_MAX_RETRIES lần.

    Tham số đi qua Redis dạng JSON nên `context` chỉ chứa kiểu JSON (chuỗi, số, list, dict).
    Hết lượt thử lại thì ghi email_logs trạng thái FAILED, không ném lỗi.
    """
    email_template = EmailTemplate(template)
    log = logger.bind(
        task_id=self.request.id, template=email_template, attempt=self.request.retries + 1
    )
    with sync_session() as session:
        service = EmailService(session, SmtpMailer(get_settings()))
        try:
            service.send(to_email, email_template, context)
        except RETRYABLE_ERRORS as exc:
            if self.request.retries < EMAIL_MAX_RETRIES:
                countdown = retry_countdown(self.request.retries)
                log.warning("email_retry", error=repr(exc), countdown=countdown)
                raise self.retry(exc=exc, countdown=countdown) from exc
            log.exception("email_failed")
            service.record_failure(to_email, email_template, exc)
            return
    log.info("email_sent")
