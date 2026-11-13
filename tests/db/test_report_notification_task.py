"""Task email S1 chạy như trong worker: đọc dữ liệu đã commit bằng session đồng bộ riêng."""

import smtplib
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.constants import TASK_MAX_RETRIES
from app.modules.departments.models import DepartmentManager
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.reports import notifications, tasks
from app.modules.reports.models import ReportRecipient
from app.modules.reports.tasks import send_report_notification
from app.modules.users.models import User, UserRole
from app.worker import celery_app, retry_countdown
from tests.factories import create_department, create_report, create_user
from tests.helpers import FakeMailer, capture_module_logs

pytestmark = pytest.mark.usefixtures("clean_after")

REPORT_DATE = date(2026, 11, 6)
MISSING_REPORT_ID = 999_999
TWO_MANAGERS = ({"full_name": "Trần Bình"}, {"full_name": "Lê Chi"})


@dataclass(frozen=True)
class Scene:
    report_id: int
    # Email người nhận theo thứ tự id, cũng là thứ tự task gửi.
    emails: list[str]


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr(tasks, "SmtpMailer", lambda _settings: fake)
    return fake


@pytest.fixture
def countdowns(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    """Thời gian chờ của từng lần task gọi retry()."""
    task = celery_app.tasks[send_report_notification.name]
    original = task.retry
    recorded: list[int | None] = []

    def spy(**kwargs: Any) -> Any:
        recorded.append(kwargs.get("countdown"))
        return original(**kwargs)

    monkeypatch.setattr(task, "retry", spy)
    return recorded


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[MutableMapping[str, Any]]:
    return capture_module_logs(monkeypatch, notifications)


async def make_scene(
    engine: AsyncEngine, recipient_fields: tuple[dict[str, Any], ...] = TWO_MANAGERS
) -> Scene:
    """Commit một báo cáo có người nhận là các manager tạo theo `recipient_fields`."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        recipients = [
            await create_user(session, **{"role": UserRole.MANAGER, **fields})
            for fields in recipient_fields
        ]
        department = await create_department(session, name="Phát triển", managers=recipients)
        author = await create_user(session, full_name="Nguyễn Văn An", department=department)
        report = await create_report(
            session,
            author=author,
            department=department,
            report_date=REPORT_DATE,
            recipients=recipients,
        )
        await session.commit()
        recipients.sort(key=lambda user: user.id)
        return Scene(report.id, [user.email for user in recipients])


async def notified_emails(engine: AsyncEngine, report_id: int) -> set[str]:
    """Email của người nhận đã có `notified_at`."""
    async with AsyncSession(engine) as session:
        statement = (
            select(User.email)
            .join(ReportRecipient, ReportRecipient.recipient_id == User.id)
            .where(ReportRecipient.report_id == report_id, ReportRecipient.notified_at.is_not(None))
        )
        return set(await session.scalars(statement))


async def email_logs(engine: AsyncEngine) -> list[tuple[str, EmailStatus, str]]:
    async with AsyncSession(engine) as session:
        rows = await session.execute(
            select(EmailLog.to_email, EmailLog.status, EmailLog.template).order_by(EmailLog.id)
        )
        return [(to_email, status, template) for to_email, status, template in rows]


def sent_logs(emails: list[str]) -> list[tuple[str, EmailStatus, str]]:
    return [(email, EmailStatus.SENT, EmailTemplate.REPORT_CREATED) for email in emails]


async def test_task_emails_every_recipient_and_marks_notified(
    engine: AsyncEngine, mailer: FakeMailer
) -> None:
    scene = await make_scene(engine)

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    assert [to_email for to_email, _ in mailer.sent] == scene.emails
    subjects = {email.subject for _, email in mailer.sent}
    assert subjects == {f"[{get_settings().app_name}] Báo cáo ngày 06/11/2026 của Nguyễn Văn An"}
    # Mỗi email chào đúng người nhận.
    assert ["Trần Bình" in email.text for _, email in mailer.sent].count(True) == 1
    assert await notified_emails(engine, scene.report_id) == set(scene.emails)
    assert await email_logs(engine) == sent_logs(scene.emails)


async def test_task_run_again_does_not_email_twice(engine: AsyncEngine, mailer: FakeMailer) -> None:
    # Ack muộn: worker dừng sau khi gửi thì task được giao lại, chạy lần nữa.
    scene = await make_scene(engine)
    send_report_notification.apply(args=(scene.report_id,))

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    assert len(mailer.sent) == len(scene.emails)
    assert await email_logs(engine) == sent_logs(scene.emails)


async def assert_second_recipient_skipped(
    engine: AsyncEngine, mailer: FakeMailer, logs: list[MutableMapping[str, Any]], scene: Scene
) -> None:
    """Chỉ người nhận đầu được gửi; người thứ hai bị bỏ qua, có warning, không có email_logs."""
    active, skipped = scene.emails
    assert [to_email for to_email, _ in mailer.sent] == [active]
    assert await notified_emails(engine, scene.report_id) == {active}
    assert skipped not in {to_email for to_email, _, _ in await email_logs(engine)}
    assert any(
        log["event"] == "report_notification_skipped" and log["reason"] == "recipient_unavailable"
        for log in logs
    )


@pytest.mark.parametrize(
    "fields",
    [{"is_active": False}, {"deleted": True}, {"password": None}, {"role": UserRole.USER}],
    ids=["locked", "deleted", "password-not-set", "no-longer-manager"],
)
async def test_task_skips_recipient_who_can_no_longer_read_report(
    engine: AsyncEngine,
    mailer: FakeMailer,
    logs: list[MutableMapping[str, Any]],
    fields: dict[str, Any],
) -> None:
    # Tạo báo cáo xong, admin khóa, xóa hay hạ role manager trước khi worker kịp gửi: họ không
    # còn đọc được báo cáo trên hệ thống thì email cũng không được lộ nội dung báo cáo.
    scene = await make_scene(engine, ({"full_name": "Trần Bình"}, fields))

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    await assert_second_recipient_skipped(engine, mailer, logs, scene)


async def test_task_skips_manager_removed_from_department(
    engine: AsyncEngine, mailer: FakeMailer, logs: list[MutableMapping[str, Any]]
) -> None:
    scene = await make_scene(engine)
    removed = scene.emails[1]
    async with AsyncSession(engine) as session:
        removed_id = await session.scalar(select(User.id).where(User.email == removed))
        await session.execute(
            delete(DepartmentManager).where(DepartmentManager.user_id == removed_id)
        )
        await session.commit()

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    await assert_second_recipient_skipped(engine, mailer, logs, scene)


async def test_task_skips_missing_report_with_warning(
    engine: AsyncEngine, mailer: FakeMailer, logs: list[MutableMapping[str, Any]]
) -> None:
    result = send_report_notification.apply(args=(MISSING_REPORT_ID,))

    assert result.successful()
    assert mailer.sent == []
    assert await email_logs(engine) == []
    [warning] = [log for log in logs if log["event"] == "report_notification_skipped"]
    assert warning["log_level"] == "warning"
    assert warning["report_id"] == MISSING_REPORT_ID


async def test_task_retries_only_recipients_not_yet_emailed(
    engine: AsyncEngine, mailer: FakeMailer, countdowns: list[int | None]
) -> None:
    scene = await make_scene(engine)
    first, second = scene.emails
    # Lần đầu: người đầu gửi lỗi, người sau vẫn được gửi. Lần thử lại chỉ gửi cho người đầu.
    mailer.errors.append(smtplib.SMTPServerDisconnected())

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    assert countdowns == [retry_countdown(0)]
    assert [to_email for to_email, _ in mailer.sent] == [second, first]
    assert await notified_emails(engine, scene.report_id) == {first, second}
    assert await email_logs(engine) == sent_logs([second, first])


async def test_task_logs_failed_for_recipient_still_failing_after_last_retry(
    engine: AsyncEngine, mailer: FakeMailer, countdowns: list[int | None]
) -> None:
    scene = await make_scene(engine)
    refused, ok = scene.emails
    mailer.refused[refused] = smtplib.SMTPRecipientsRefused({refused: (550, b"no user")})

    result = send_report_notification.apply(args=(scene.report_id,))

    assert result.successful()
    assert countdowns == [retry_countdown(n) for n in range(TASK_MAX_RETRIES)]
    assert [to_email for to_email, _ in mailer.sent] == [ok]
    assert await notified_emails(engine, scene.report_id) == {ok}
    logs = await email_logs(engine)
    assert logs == [*sent_logs([ok]), (refused, EmailStatus.FAILED, EmailTemplate.REPORT_CREATED)]
