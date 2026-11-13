"""Cấp link đặt mật khẩu lần đầu (S2) trong Celery worker: AccountSetupService và task gửi email."""

import re
import smtplib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import (
    ONE_TIME_TOKEN_PATTERN,
    SETUP_PASSWORD_PATH,
    SETUP_PASSWORD_TOKEN_EXPIRE_HOURS,
    TASK_MAX_RETRIES,
)
from app.core.security import hash_one_time_token
from app.modules.auth import tasks
from app.modules.auth.models import UserToken, UserTokenPurpose
from app.modules.auth.service import AccountSetupService
from app.modules.auth.tasks import send_account_setup_email
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.users.models import User
from tests.helpers import FakeMailer, capture_module_logs, use_test_worker

NOW = datetime(2026, 11, 7, 8, 0, tzinfo=UTC)
SETUP_URL = f"{str(get_settings().frontend_url).rstrip('/')}{SETUP_PASSWORD_PATH}?token="
# Token trên link trong email: lấy ra để đối chiếu với hash trong DB.
TOKEN_IN_LINK = re.compile(re.escape(SETUP_URL) + ONE_TIME_TOKEN_PATTERN[1:-1])


def _add_user(session: Session, **fields: Any) -> int:
    user = User(email="binh@example.com", full_name="Trần Thị Bình", **fields)
    session.add(user)
    session.flush()
    return user.id


def _tokens(session: Session, user_id: int) -> list[UserToken]:
    return list(session.scalars(select(UserToken).where(UserToken.user_id == user_id)))


def _email_logs(session: Session) -> list[EmailLog]:
    return list(session.scalars(select(EmailLog).order_by(EmailLog.id)))


def _token_in(text: str) -> str:
    match = TOKEN_IN_LINK.search(text)
    assert match is not None, text
    return match.group().removeprefix(SETUP_URL)


# User không còn cần đặt mật khẩu: không cấp link, task bỏ qua.
NO_LONGER_NEEDED = pytest.mark.parametrize(
    "fields",
    [{"password_hash": "argon2-hash"}, {"is_active": False}, {"deleted_at": NOW}],
    ids=["password-already-set", "inactive", "deleted"],
)


# AccountSetupService


def test_issue_link_stores_only_hash_with_expiry(sync_db_session: Session) -> None:
    user_id = _add_user(sync_db_session)

    link = AccountSetupService(sync_db_session).issue_link(user_id, NOW)

    assert link is not None
    assert (link.email, link.full_name) == ("binh@example.com", "Trần Thị Bình")
    token = _token_in(link.url)
    [stored] = _tokens(sync_db_session, user_id)
    assert stored.token_hash == hash_one_time_token(token)
    assert stored.purpose == UserTokenPurpose.SETUP_PASSWORD
    assert stored.expires_at == NOW + timedelta(hours=SETUP_PASSWORD_TOKEN_EXPIRE_HOURS)
    assert stored.used_at is None


def test_issue_link_again_replaces_previous_link(sync_db_session: Session) -> None:
    user_id = _add_user(sync_db_session)
    service = AccountSetupService(sync_db_session)
    first = service.issue_link(user_id, NOW)

    second = service.issue_link(user_id, NOW)

    assert first is not None
    assert second is not None
    [stored] = _tokens(sync_db_session, user_id)
    assert stored.token_hash == hash_one_time_token(_token_in(second.url))
    assert stored.token_hash != hash_one_time_token(_token_in(first.url))


@NO_LONGER_NEEDED
def test_issue_link_skips_user_who_no_longer_needs_it(
    sync_db_session: Session, fields: dict[str, Any]
) -> None:
    user_id = _add_user(sync_db_session, **fields)

    assert AccountSetupService(sync_db_session).issue_link(user_id, NOW) is None
    assert _tokens(sync_db_session, user_id) == []


def test_issue_link_skips_unknown_user(sync_db_session: Session) -> None:
    assert AccountSetupService(sync_db_session).issue_link(1, NOW) is None


# Task send_account_setup_email


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch, sync_db_session: Session) -> FakeMailer:
    return use_test_worker(monkeypatch, tasks, sync_db_session)


def test_task_emails_setup_link_to_user(mailer: FakeMailer, sync_db_session: Session) -> None:
    user_id = _add_user(sync_db_session)

    result = send_account_setup_email.apply(args=(user_id,))

    assert result.successful()
    [(to_email, email)] = mailer.sent
    assert to_email == "binh@example.com"
    assert "Trần Thị Bình" in email.text
    assert f"{SETUP_PASSWORD_TOKEN_EXPIRE_HOURS} giờ" in email.text
    token = _token_in(email.text)
    assert _token_in(email.html) == token
    [stored] = _tokens(sync_db_session, user_id)
    assert stored.token_hash == hash_one_time_token(token)
    [log] = _email_logs(sync_db_session)
    assert (log.template, log.status) == (EmailTemplate.ACCOUNT_SETUP, EmailStatus.SENT)


@NO_LONGER_NEEDED
def test_task_skips_user_who_no_longer_needs_it_with_warning(
    mailer: FakeMailer,
    sync_db_session: Session,
    fields: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Task chạy lại sau khi user đã đặt mật khẩu, hay admin vừa khóa, xóa tài khoản: không gửi.
    user_id = _add_user(sync_db_session, **fields)
    logs = capture_module_logs(monkeypatch, tasks)

    result = send_account_setup_email.apply(args=(user_id,))

    assert result.successful()
    assert mailer.sent == []
    assert _email_logs(sync_db_session) == []
    [skipped] = [log for log in logs if log["event"] == "account_setup_email_skipped"]
    assert (skipped["log_level"], skipped["user_id"]) == ("warning", user_id)


def test_task_retry_sends_new_link_and_drops_unsent_one(
    mailer: FakeMailer, sync_db_session: Session
) -> None:
    user_id = _add_user(sync_db_session)
    mailer.errors.append(smtplib.SMTPServerDisconnected())

    result = send_account_setup_email.apply(args=(user_id,))

    assert result.successful()
    [(_, email)] = mailer.sent
    # Link của lần gửi lỗi không còn: chỉ link trong email đã gửi dùng được.
    [stored] = _tokens(sync_db_session, user_id)
    assert stored.token_hash == hash_one_time_token(_token_in(email.text))


def test_task_logs_failed_after_last_retry(mailer: FakeMailer, sync_db_session: Session) -> None:
    user_id = _add_user(sync_db_session)
    refused = smtplib.SMTPRecipientsRefused({"binh@example.com": (550, b"no user")})
    mailer.errors.extend([refused] * (TASK_MAX_RETRIES + 1))

    result = send_account_setup_email.apply(args=(user_id,))

    assert result.successful()
    assert mailer.sent == []
    [log] = _email_logs(sync_db_session)
    assert (log.template, log.status) == (EmailTemplate.ACCOUNT_SETUP, EmailStatus.FAILED)
