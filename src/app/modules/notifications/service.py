from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import EMAIL_ERROR_MAX_LENGTH
from app.modules.notifications.mailer import Mailer
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.notifications.rendering import render_email
from app.modules.notifications.repository import EmailLogRepository


class EmailService:
    """Dựng email từ template, gửi, ghi kết quả vào email_logs. Dùng trong Celery task."""

    def __init__(self, session: Session, mailer: Mailer) -> None:
        self.session = session
        self.mailer = mailer
        self.logs = EmailLogRepository(session)

    def send(self, to_email: str, template: EmailTemplate, context: Mapping[str, Any]) -> EmailLog:
        """Gửi rồi ghi log SENT. Gửi lỗi thì ném lỗi ra, không ghi log: task còn thử lại."""
        self.mailer.send(to_email, render_email(template, context))
        return self._record(to_email, template, EmailStatus.SENT)

    def record_failure(self, to_email: str, template: EmailTemplate, error: Exception) -> EmailLog:
        """Ghi log FAILED khi đã hết lượt thử lại."""
        message = f"{type(error).__name__}: {error}"[:EMAIL_ERROR_MAX_LENGTH]
        return self._record(to_email, template, EmailStatus.FAILED, error=message)

    def _record(
        self, to_email: str, template: EmailTemplate, status: EmailStatus, error: str | None = None
    ) -> EmailLog:
        log = EmailLog(to_email=to_email, template=template, status=status, error=error)
        self.logs.add(log)
        self.session.commit()
        return log
