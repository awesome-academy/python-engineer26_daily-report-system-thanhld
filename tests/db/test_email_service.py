import smtplib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import EMAIL_ERROR_MAX_LENGTH
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.notifications.service import EmailService
from tests.helpers import FakeMailer

CONTEXT = {"requested_at": "08:30:00 06/11/2026"}


def _logs(session: Session) -> list[EmailLog]:
    return list(session.scalars(select(EmailLog).order_by(EmailLog.id)))


def test_send_renders_template_sends_and_logs_sent(sync_db_session: Session) -> None:
    mailer = FakeMailer()

    EmailService(sync_db_session, mailer).send("an@example.com", EmailTemplate.TEST, CONTEXT)

    [(to_email, email)] = mailer.sent
    assert to_email == "an@example.com"
    assert CONTEXT["requested_at"] in email.text
    [log] = _logs(sync_db_session)
    assert (log.to_email, log.template, log.status, log.error) == (
        "an@example.com",
        EmailTemplate.TEST,
        EmailStatus.SENT,
        None,
    )


def test_send_failure_raises_without_logging(sync_db_session: Session) -> None:
    # Còn lượt thử lại thì chưa ghi log; chỉ ghi FAILED khi task đã hết lượt.
    mailer = FakeMailer(errors=[smtplib.SMTPServerDisconnected("mất kết nối")])

    with pytest.raises(smtplib.SMTPServerDisconnected):
        EmailService(sync_db_session, mailer).send("an@example.com", EmailTemplate.TEST, CONTEXT)

    assert _logs(sync_db_session) == []


def test_record_failure_logs_error_type_and_truncated_message(sync_db_session: Session) -> None:
    error = ConnectionRefusedError("x" * (EMAIL_ERROR_MAX_LENGTH * 2))

    EmailService(sync_db_session, FakeMailer()).record_failure(
        "an@example.com", EmailTemplate.TEST, error
    )

    [log] = _logs(sync_db_session)
    assert log.status == EmailStatus.FAILED
    assert log.error is not None
    assert log.error.startswith("ConnectionRefusedError: xxx")
    assert len(log.error) == EMAIL_ERROR_MAX_LENGTH
