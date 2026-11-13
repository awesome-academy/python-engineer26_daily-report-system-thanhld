"""Celery task của module xác thực: email link đặt mật khẩu lần đầu (S2)."""

from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from app.core.config import get_settings
from app.core.constants import SETUP_PASSWORD_TOKEN_EXPIRE_HOURS, TASK_MAX_RETRIES
from app.core.database import sync_session
from app.modules.auth.service import AccountSetupService
from app.modules.notifications.mailer import RETRYABLE_ERRORS, SmtpMailer
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.service import EmailService
from app.worker import celery_app, retry_or_give_up

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="auth.send_account_setup_email", max_retries=TASK_MAX_RETRIES)
def send_account_setup_email(self: Task[Any, Any], user_id: int) -> None:
    """Gửi link đặt mật khẩu cho user admin vừa tạo; lỗi SMTP thì thử lại như `send_email`.

    Mỗi lần chạy (kể cả thử lại, worker giao lại task) cấp link mới và xóa link cũ. User không còn
    cần đặt mật khẩu (bị xóa, bị khóa, đã đặt xong) thì bỏ qua, không gửi.
    """
    template = EmailTemplate.ACCOUNT_SETUP
    log = logger.bind(task_id=self.request.id, user_id=user_id, attempt=self.request.retries + 1)
    with sync_session() as session:
        link = AccountSetupService(session).issue_link(user_id, datetime.now(UTC))
        if link is None:
            log.warning("account_setup_email_skipped")
            return
        context = {
            "full_name": link.full_name,
            "email": link.email,
            "setup_url": link.url,
            "expire_hours": SETUP_PASSWORD_TOKEN_EXPIRE_HOURS,
        }
        service = EmailService(session, SmtpMailer(get_settings()))
        try:
            service.send(link.email, template, context)
        except RETRYABLE_ERRORS as exc:
            retry_or_give_up(self, exc)
            log.exception("email_failed")
            service.record_failure(link.email, template, exc)
            return
    log.info("email_sent")
