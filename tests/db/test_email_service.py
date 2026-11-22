import asyncio
import smtplib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import EMAIL_ERROR_MAX_LENGTH
from app.core.database import sync_session
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.notifications.repository import EmailLogRepository
from app.modules.notifications.service import EmailService
from tests.helpers import LOCK_WAIT_SECONDS, FakeMailer

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
    # Không giữ dedup_key: chạy lại vẫn gửi được email chưa tới.
    assert log.dedup_key is None
    assert log.error is not None
    assert log.error.startswith("ConnectionRefusedError: xxx")
    assert len(log.error) == EMAIL_ERROR_MAX_LENGTH


DEDUP_KEY = "monthly:2026-10:dept:1:user:2"


def _send_once(session: Session, mailer: FakeMailer) -> bool:
    return EmailService(session, mailer).send_once(
        "an@example.com", EmailTemplate.TEST, CONTEXT, DEDUP_KEY
    )


def test_send_once_sends_and_logs_dedup_key(sync_db_session: Session) -> None:
    mailer = FakeMailer()

    assert _send_once(sync_db_session, mailer) is True

    assert [to_email for to_email, _ in mailer.sent] == ["an@example.com"]
    [log] = _logs(sync_db_session)
    assert (log.to_email, log.status, log.dedup_key) == (
        "an@example.com",
        EmailStatus.SENT,
        DEDUP_KEY,
    )


def test_send_once_skips_key_already_sent(sync_db_session: Session) -> None:
    mailer = FakeMailer()
    _send_once(sync_db_session, mailer)

    assert _send_once(sync_db_session, mailer) is False

    assert len(mailer.sent) == 1
    assert len(_logs(sync_db_session)) == 1


def test_send_once_failure_releases_key_for_retry(sync_db_session: Session) -> None:
    mailer = FakeMailer(errors=[smtplib.SMTPServerDisconnected("mất kết nối")])

    with pytest.raises(smtplib.SMTPServerDisconnected):
        _send_once(sync_db_session, mailer)

    # Dòng giữ key bị rollback: lần thử lại gửi được, không bị coi là đã gửi.
    assert _logs(sync_db_session) == []
    assert _send_once(sync_db_session, mailer) is True
    assert len(mailer.sent) == 1


@pytest.mark.usefixtures("clean_after")
async def test_send_once_waits_for_same_key_in_flight_then_skips() -> None:
    # Hai task cùng key chạy song song (Beat chạy lại, worker giao lại task): task đầu đã ghi key
    # và đang gửi SMTP. Task sau phải chờ rồi bỏ qua, không đọc thấy "chưa có" rồi gửi lần nữa.
    mailer = FakeMailer()
    with sync_session() as first, sync_session() as second:
        assert EmailLogRepository(first).claim("an@example.com", EmailTemplate.TEST, DEDUP_KEY)
        pending = asyncio.create_task(asyncio.to_thread(_send_once, second, mailer))
        await asyncio.wait({pending}, timeout=LOCK_WAIT_SECONDS)
        assert not pending.done()

        first.commit()

        assert await pending is False
    assert mailer.sent == []
