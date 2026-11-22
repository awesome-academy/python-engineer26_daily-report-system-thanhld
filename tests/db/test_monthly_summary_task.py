"""Task email thống kê tháng S3 chạy như trong worker: đọc dữ liệu đã commit bằng session riêng."""

import re
import smtplib
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.constants import TASK_MAX_RETRIES
from app.core.workdays import is_working_day
from app.modules.departments.models import Department
from app.modules.notifications.models import EmailLog, EmailStatus, EmailTemplate
from app.modules.notifications.rendering import RenderedEmail
from app.modules.reports import monthly_summary, tasks
from app.modules.reports.repository import MonthlySummaryRepository
from app.modules.reports.tasks import send_monthly_summaries
from app.modules.users.models import User, UserRole
from app.worker import celery_app, retry_countdown
from tests.factories import create_department, create_report, create_user
from tests.helpers import FakeMailer, capture_module_logs

pytestmark = pytest.mark.usefixtures("clean_after")

MONTH = "2026-10"
OCTOBER_FIRST = date(2026, 10, 1)
# Tạo tài khoản từ tháng trước: cả tháng 10 (22 ngày làm việc) đều phải nộp.
JOINED = datetime(2026, 9, 1, tzinfo=UTC)
OCTOBER_WORKING_DAYS = [
    OCTOBER_FIRST + timedelta(days=n)
    for n in range(31)
    if is_working_day(OCTOBER_FIRST + timedelta(days=n))
]
# Manager còn liên kết với bộ phận nhưng không đọc được báo cáo: không nhận thống kê (như S1).
UNAVAILABLE_MANAGERS: tuple[dict[str, Any], ...] = (
    {"is_active": False},
    {"deleted": True},
    {"password": None},
    {"role": UserRole.USER},
)
# Dòng đầu email: thời điểm tính số liệu theo giờ Việt Nam.
COMPUTED_AT_LINE = re.compile(r", số liệu tính đến \d{2}:\d{2} \d{2}/\d{2}/\d{4}\.$", re.M)


@dataclass(frozen=True)
class Recipient:
    department_id: int
    user_id: int
    email: str


@dataclass(frozen=True)
class Scene:
    dev_id: int
    qa_id: int
    hr_id: int
    # Theo thứ tự task gửi: bộ phận, rồi id manager.
    recipients: list[Recipient]

    @property
    def emails(self) -> list[str]:
        return [recipient.email for recipient in self.recipients]


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr(tasks, "SmtpMailer", lambda _settings: fake)
    return fake


@pytest.fixture
def retries(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Tham số (`args`, `countdown`) của từng lần task gọi retry()."""
    task = celery_app.tasks[send_monthly_summaries.name]
    original = task.retry
    recorded: list[dict[str, Any]] = []

    def spy(**kwargs: Any) -> Any:
        recorded.append({"args": kwargs.get("args"), "countdown": kwargs.get("countdown")})
        return original(**kwargs)

    monkeypatch.setattr(task, "retry", spy)
    return recorded


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[MutableMapping[str, Any]]:
    return capture_module_logs(monkeypatch, monthly_summary)


async def employee(
    session: AsyncSession,
    department: Department,
    full_name: str,
    report_dates: Sequence[date] = (),
    **fields: Any,
) -> User:
    user = await create_user(
        session, full_name=full_name, department=department, **{"created_at": JOINED, **fields}
    )
    for day in report_dates:
        await create_report(session, author=user, department=department, report_date=day)
    return user


async def make_scene(engine: AsyncEngine) -> Scene:
    """DEV (2 manager, đủ loại nhân viên), QA (2 manager), HR (không manager).

    Trần Bình quản lý cả DEV và QA: nhận một email cho mỗi bộ phận.
    """
    async with AsyncSession(engine, expire_on_commit=False) as session:
        binh, chi, minh = [
            await create_user(session, full_name=name, role=UserRole.MANAGER)
            for name in ("Trần Bình", "Lê Chi", "Vũ Minh")
        ]
        unavailable = [
            await create_user(session, **{"role": UserRole.MANAGER, **fields})
            for fields in UNAVAILABLE_MANAGERS
        ]
        dev = await create_department(
            session, name="Phát triển", managers=[binh, chi, *unavailable]
        )
        qa = await create_department(session, name="Kiểm thử", managers=[binh, minh])
        hr = await create_department(session, name="Nhân sự")

        # Thứ 7 (3/10), ngày của tháng trước, tháng sau không tính: đã nộp 2 ngày.
        await employee(
            session,
            dev,
            "Nguyễn Văn An",
            [
                date(2026, 9, 30),
                OCTOBER_FIRST,
                date(2026, 10, 2),
                date(2026, 10, 3),
                date(2026, 11, 2),
            ],
        )
        # Tạo lúc 01:30 ngày 15/10 giờ Việt Nam (14/10 theo UTC): phải nộp từ 15/10, 12 ngày.
        # Báo cáo ngày 14/10 (trước khi có tài khoản, dữ liệu cũ) không tính.
        await employee(
            session,
            dev,
            "Hoàng Dũng",
            [date(2026, 10, 14), date(2026, 10, 15)],
            created_at=datetime(2026, 10, 14, 18, 30, tzinfo=UTC),
        )
        await employee(session, dev, "Đỗ Hà", is_active=False)
        # Không có trong thống kê: đã xóa, không phải nhân viên, tạo sau khi hết tháng, tạo
        # vào thứ 7 cuối tháng (không còn ngày phải nộp).
        await employee(session, dev, "Đã Xóa", [OCTOBER_FIRST], deleted=True)
        await employee(session, dev, "Quản Lý Thành Viên", role=UserRole.MANAGER)
        await employee(session, dev, "Mới Vào", created_at=datetime(2026, 11, 1, tzinfo=UTC))
        await employee(session, dev, "Vào Thứ Bảy", created_at=datetime(2026, 10, 31, tzinfo=UTC))

        await employee(session, qa, "Phạm Giang", OCTOBER_WORKING_DAYS)
        # Đã nộp ngày 5/10 khi còn ở DEV rồi chuyển sang QA: tính ở bộ phận hiện tại (QA).
        moved = await employee(session, qa, "Lý Chuyển")
        await create_report(session, author=moved, department=dev, report_date=date(2026, 10, 5))
        await employee(session, hr, "Võ Lan")
        # Bộ phận có manager nhưng không có nhân viên, bộ phận đã xóa: không gửi.
        await create_department(session, name="Trống", managers=[binh])
        deleted = await create_department(session, name="Đã xóa", managers=[binh], deleted=True)
        await employee(session, deleted, "Ở Bộ Phận Đã Xóa")
        await session.commit()

        recipients = [(dev, binh), (dev, chi), (qa, binh), (qa, minh)]
        return Scene(
            dev_id=dev.id,
            qa_id=qa.id,
            hr_id=hr.id,
            recipients=[Recipient(d.id, user.id, user.email) for d, user in recipients],
        )


def summary_lines(email: RenderedEmail) -> list[str]:
    return [line for line in email.text.splitlines() if line.startswith("- ")]


async def email_logs(engine: AsyncEngine) -> list[tuple[str, EmailStatus, str, str | None]]:
    async with AsyncSession(engine) as session:
        rows = await session.execute(
            select(
                EmailLog.to_email, EmailLog.status, EmailLog.template, EmailLog.dedup_key
            ).order_by(EmailLog.id)
        )
        return [(to_email, status, template, key) for to_email, status, template, key in rows]


def sent_logs(scene: Scene, indexes: list[int]) -> list[tuple[str, EmailStatus, str, str | None]]:
    # Viết lại dạng key như docs/database.md, không dựng từ hằng số của code đang test.
    return [
        (
            scene.recipients[i].email,
            EmailStatus.SENT,
            EmailTemplate.MONTHLY_SUMMARY,
            f"monthly:{MONTH}:dept:{scene.recipients[i].department_id}"
            f":user:{scene.recipients[i].user_id}",
        )
        for i in indexes
    ]


def fail_stats_query(monkeypatch: pytest.MonkeyPatch, times: int) -> list[int]:
    """Câu thống kê lỗi mất kết nối DB `times` lần đầu; trả về list đếm số lần gọi."""
    original = MonthlySummaryRepository.list_employee_stats
    calls: list[int] = []

    def flaky(self: MonthlySummaryRepository, *args: Any) -> Any:
        calls.append(1)
        if len(calls) <= times:
            raise OperationalError("SELECT ...", None, Exception("server closed the connection"))
        return original(self, *args)

    monkeypatch.setattr(MonthlySummaryRepository, "list_employee_stats", flaky)
    return calls


async def test_task_emails_department_summary_to_each_manager(
    engine: AsyncEngine, mailer: FakeMailer, logs: list[MutableMapping[str, Any]]
) -> None:
    scene = await make_scene(engine)

    result = send_monthly_summaries.apply(args=(MONTH,))

    assert result.successful()
    assert [to_email for to_email, _ in mailer.sent] == scene.emails
    (_, dev_binh), (_, dev_chi), (_, qa_binh), (_, qa_minh) = mailer.sent
    app_name = get_settings().app_name
    # Manager của hai bộ phận nhận hai email riêng.
    assert dev_binh.subject == f"[{app_name}] Thống kê báo cáo tháng 10/2026 của bộ phận Phát triển"
    assert qa_binh.subject == f"[{app_name}] Thống kê báo cáo tháng 10/2026 của bộ phận Kiểm thử"
    assert "Xin chào Trần Bình," in dev_binh.text
    assert "Xin chào Lê Chi," in dev_chi.text
    assert COMPUTED_AT_LINE.search(dev_binh.text)
    # Sắp theo tên không dấu; 3/56 ngày phải nộp là 5,36%, làm tròn xuống.
    assert "0/3 nhân viên nộp đủ, cả bộ phận đã nộp 5% tổng số ngày phải nộp." in dev_binh.text
    assert summary_lines(dev_binh) == [
        "- Đỗ Hà (đã khóa): đã nộp 0/22 ngày (0%), thiếu 22 ngày",
        "- Hoàng Dũng: đã nộp 1/12 ngày (8%), thiếu 11 ngày",
        "- Nguyễn Văn An: đã nộp 2/22 ngày (9%), thiếu 20 ngày",
    ]
    assert summary_lines(dev_chi) == summary_lines(dev_binh)
    assert "1/2 nhân viên nộp đủ, cả bộ phận đã nộp 52% tổng số ngày phải nộp." in qa_binh.text
    assert summary_lines(qa_binh) == [
        "- Lý Chuyển: đã nộp 1/22 ngày (4%), thiếu 21 ngày",
        "- Phạm Giang: đã nộp 22/22 ngày (100%), thiếu 0 ngày",
    ]
    assert summary_lines(qa_minh) == summary_lines(qa_binh)
    assert await email_logs(engine) == sent_logs(scene, [0, 1, 2, 3])
    # Bộ phận có nhân viên mà không ai nhận thống kê: ghi warning cho admin.
    [warning] = [log for log in logs if log["event"] == "monthly_summary_skipped"]
    assert warning["log_level"] == "warning"
    assert (warning["month"], warning["department_id"], warning["reason"]) == (
        MONTH,
        scene.hr_id,
        "no_recipient",
    )


async def test_task_run_again_does_not_email_twice(engine: AsyncEngine, mailer: FakeMailer) -> None:
    # Beat chạy lại, ack muộn (worker dừng sau khi gửi): task chạy lần nữa cho cùng tháng.
    scene = await make_scene(engine)
    send_monthly_summaries.apply(args=(MONTH,))

    result = send_monthly_summaries.apply(args=(MONTH,))

    assert result.successful()
    assert len(mailer.sent) == len(scene.emails)
    assert await email_logs(engine) == sent_logs(scene, [0, 1, 2, 3])


async def test_task_without_month_summarizes_previous_month_and_retries_same_month(
    engine: AsyncEngine,
    mailer: FakeMailer,
    retries: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Beat gọi không tham số lúc 08:00 ngày 1/11. Lần thử lại chạy khi đồng hồ đã sang 1/12 (task
    # nằm chờ qua tháng): vẫn thống kê tháng 10 vì lần thử lại truyền đúng tháng đã tính.
    scene = await make_scene(engine)
    days = [date(2026, 11, 1), date(2026, 12, 1)]
    monkeypatch.setattr(tasks, "local_today", lambda: days.pop(0) if len(days) > 1 else days[0])
    mailer.errors.append(smtplib.SMTPServerDisconnected())

    result = send_monthly_summaries.apply()

    assert result.successful()
    assert retries == [{"args": (MONTH,), "countdown": retry_countdown(0)}]
    # Lần đầu: email đầu lỗi, các email sau vẫn gửi. Lần thử lại chỉ gửi email còn thiếu.
    assert [to_email for to_email, _ in mailer.sent] == [*scene.emails[1:], scene.emails[0]]
    assert {email.subject.split(" của ")[0] for _, email in mailer.sent} == {
        f"[{get_settings().app_name}] Thống kê báo cáo tháng 10/2026"
    }
    assert await email_logs(engine) == sent_logs(scene, [1, 2, 3, 0])


async def test_task_logs_failed_without_key_after_last_retry_so_next_run_sends(
    engine: AsyncEngine, mailer: FakeMailer, retries: list[dict[str, Any]]
) -> None:
    scene = await make_scene(engine)
    # Lê Chi chỉ quản lý DEV: một email luôn lỗi.
    refused = scene.emails[1]
    mailer.refused[refused] = smtplib.SMTPRecipientsRefused({refused: (550, b"no user")})

    result = send_monthly_summaries.apply(args=(MONTH,))

    assert result.successful()
    assert [item["countdown"] for item in retries] == [
        retry_countdown(n) for n in range(TASK_MAX_RETRIES)
    ]
    failed = (refused, EmailStatus.FAILED, EmailTemplate.MONTHLY_SUMMARY, None)
    assert await email_logs(engine) == [*sent_logs(scene, [0, 2, 3]), failed]

    # Sửa xong lỗi rồi chạy lại cho tháng đó: chỉ gửi email chưa tới.
    del mailer.refused[refused]
    send_monthly_summaries.apply(args=(MONTH,))

    assert [to_email for to_email, _ in mailer.sent][-1] == refused
    assert len(mailer.sent) == len(scene.emails)
    assert await email_logs(engine) == [
        *sent_logs(scene, [0, 2, 3]),
        failed,
        *sent_logs(scene, [1]),
    ]


async def test_task_retries_same_month_when_database_unavailable(
    engine: AsyncEngine,
    mailer: FakeMailer,
    retries: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DB khởi động lại đúng lúc Beat chạy: không mất cả lượt gửi của tháng.
    scene = await make_scene(engine)
    monkeypatch.setattr(tasks, "local_today", lambda: date(2026, 11, 1))
    fail_stats_query(monkeypatch, times=1)

    result = send_monthly_summaries.apply()

    assert result.successful()
    assert retries == [{"args": (MONTH,), "countdown": retry_countdown(0)}]
    assert [to_email for to_email, _ in mailer.sent] == scene.emails


async def test_task_fails_after_last_retry_when_database_stays_unavailable(
    engine: AsyncEngine,
    mailer: FakeMailer,
    retries: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_scene(engine)
    calls = fail_stats_query(monkeypatch, times=TASK_MAX_RETRIES + 1)

    result = send_monthly_summaries.apply(args=(MONTH,))

    # Không còn DB để ghi FAILED: task báo lỗi (log của Celery), chạy lại tay khi DB đã lên.
    assert result.failed()
    assert isinstance(result.result, OperationalError)
    assert len(calls) == TASK_MAX_RETRIES + 1
    assert len(retries) == TASK_MAX_RETRIES
    assert mailer.sent == []


async def test_task_rejects_month_not_finished(
    engine: AsyncEngine, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_scene(engine)
    monkeypatch.setattr(tasks, "local_today", lambda: date(2026, 11, 22))

    result = send_monthly_summaries.apply(args=("2026-11",))

    assert result.failed()
    assert isinstance(result.result, ValueError)
    assert mailer.sent == []
    assert await email_logs(engine) == []
