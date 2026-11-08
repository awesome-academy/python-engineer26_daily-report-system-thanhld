"""Celery task gửi email."""

from typing import Any

import structlog
from celery import Task

from app.core.config import get_settings
from app.core.constants import TASK_MAX_RETRIES
from app.core.database import sync_session
from app.modules.notifications.mailer import RETRYABLE_ERRORS, SmtpMailer
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.service import EmailService
from app.worker import celery_app, retry_or_give_up

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="notifications.send_email", max_retries=TASK_MAX_RETRIES)
def send_email(self: Task[Any, Any], to_email: str, template: str, context: dict[str, Any]) -> None:
    """Gửi một email theo template; lỗi thì thử lại tối đa TASK_MAX_RETRIES lần.

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
            retry_or_give_up(self, exc)
            log.exception("email_failed")
            service.record_failure(to_email, email_template, exc)
            return
    log.info("email_sent")
