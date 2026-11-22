from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate


class EmailLogRepository:
    """Truy vấn bảng email_logs bằng session đồng bộ (Celery worker)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, log: EmailLog) -> None:
        self.session.add(log)
        self.session.flush()

    def claim(self, to_email: str, template: EmailTemplate, dedup_key: str) -> bool:
        """Ghi dòng SENT giữ `dedup_key` (chưa commit); key đã có dòng thì không ghi, trả False.

        Transaction khác vừa ghi cùng key mà chưa kết thúc thì câu lệnh chờ ở unique index:
        transaction đó commit thì trả False, rollback thì ghi được.
        """
        statement = (
            insert(EmailLog)
            .values(
                to_email=to_email, template=template, status=EmailStatus.SENT, dedup_key=dedup_key
            )
            .on_conflict_do_nothing(index_elements=[EmailLog.dedup_key])
            .returning(EmailLog.id)
        )
        return self.session.scalar(statement) is not None
