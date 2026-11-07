from sqlalchemy.orm import Session

from app.modules.notifications.models import EmailLog


class EmailLogRepository:
    """Truy vấn bảng email_logs bằng session đồng bộ (Celery worker)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, log: EmailLog) -> None:
        self.session.add(log)
        self.session.flush()
