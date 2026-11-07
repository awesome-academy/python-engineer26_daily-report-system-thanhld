import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import TASK_MAX_RETRIES
from app.modules.notifications import tasks
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.notifications.tasks import send_email
from app.worker import celery_app, retry_countdown
from tests.helpers import FakeMailer

ARGS = ("an@example.com", EmailTemplate.TEST.value, {"requested_at": "08:30:00 06/11/2026"})


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch, sync_db_session: Session) -> FakeMailer:
    """Task dùng session test (rollback sau test) và mailer giả thay cho SMTP thật."""
    fake = FakeMailer()

    @contextmanager
    def session() -> Iterator[Session]:
        yield sync_db_session

    monkeypatch.setattr(tasks, "sync_session", session)
    monkeypatch.setattr(tasks, "SmtpMailer", lambda _settings: fake)
    return fake


def _logs(session: Session) -> list[EmailLog]:
    return list(session.scalars(select(EmailLog).order_by(EmailLog.id)))


def test_task_sends_email_and_logs_sent(mailer: FakeMailer, sync_db_session: Session) -> None:
    result = send_email.apply(args=ARGS)

    assert result.successful()
    assert [to_email for to_email, _ in mailer.sent] == ["an@example.com"]
    [log] = _logs(sync_db_session)
    assert log.status == EmailStatus.SENT


@pytest.fixture
def countdowns(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    """Thời gian chờ của từng lần task gọi retry()."""
    task = celery_app.tasks[send_email.name]
    original = task.retry
    recorded: list[int | None] = []

    def spy(**kwargs: Any) -> Any:
        recorded.append(kwargs.get("countdown"))
        return original(**kwargs)

    monkeypatch.setattr(task, "retry", spy)
    return recorded


@pytest.mark.parametrize(
    "error",
    [smtplib.SMTPServerDisconnected(), ConnectionRefusedError(), TimeoutError()],
    ids=["smtp-error", "connection-refused", "timeout"],
)
def test_task_retries_with_backoff_then_sends(
    mailer: FakeMailer, sync_db_session: Session, countdowns: list[int | None], error: Exception
) -> None:
    mailer.errors.extend([error] * TASK_MAX_RETRIES)

    # apply() chạy task tại chỗ, lần thử lại chạy ngay (bỏ qua countdown), nên một lệnh apply()
    # đi hết các lần thử như worker.
    result = send_email.apply(args=ARGS)

    assert result.successful()
    assert countdowns == [retry_countdown(n) for n in range(TASK_MAX_RETRIES)]
    assert len(mailer.sent) == 1
    [log] = _logs(sync_db_session)
    assert log.status == EmailStatus.SENT


def test_task_logs_failed_after_last_retry(
    mailer: FakeMailer, sync_db_session: Session, countdowns: list[int | None]
) -> None:
    refused = smtplib.SMTPRecipientsRefused({"an@example.com": (550, b"no user")})
    mailer.errors.extend([refused] * (TASK_MAX_RETRIES + 1))

    result = send_email.apply(args=ARGS)

    assert result.successful()
    assert len(countdowns) == TASK_MAX_RETRIES
    assert mailer.sent == []
    [log] = _logs(sync_db_session)
    assert log.status == EmailStatus.FAILED
    assert log.error is not None
    assert log.error.startswith("SMTPRecipientsRefused")


def test_task_does_not_retry_unknown_template(mailer: FakeMailer, sync_db_session: Session) -> None:
    result = send_email.apply(args=("an@example.com", "khong-co", {}))

    assert result.failed()
    assert isinstance(result.result, ValueError)
    assert mailer.sent == []
    assert _logs(sync_db_session) == []
