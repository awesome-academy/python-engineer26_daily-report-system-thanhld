from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import RefreshToken, UserToken, UserTokenPurpose
from app.modules.departments.models import DEPARTMENT_CODE_UNIQUE_INDEX, Department
from app.modules.notifications.models import EmailLog, EmailStatus
from app.modules.reports.models import REPORT_AUTHOR_DATE_UNIQUE, DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole
from tests.factories import create_department, create_report, create_user

TODAY = date(2026, 10, 26)


async def test_department_loads_members_and_managers_both_ways(db_session: AsyncSession) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, code="DEV", managers=[manager])
    member = await create_user(db_session, department=department)
    db_session.expunge_all()

    loaded = await db_session.scalar(
        select(Department)
        .where(Department.code == "DEV")
        .options(selectinload(Department.members), selectinload(Department.managers))
    )
    managed = await db_session.scalar(
        select(User).where(User.id == manager.id).options(selectinload(User.managed_departments))
    )

    assert loaded is not None
    assert [user.id for user in loaded.members] == [member.id]
    assert [user.id for user in loaded.managers] == [manager.id]
    assert managed is not None
    assert [d.code for d in managed.managed_departments] == ["DEV"]


async def test_report_loads_author_department_and_recipients(db_session: AsyncSession) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    author = await create_user(db_session, department=department)
    await create_report(
        db_session, author=author, department=department, report_date=TODAY, recipients=[manager]
    )
    db_session.expunge_all()

    report = await db_session.scalar(
        select(DailyReport).options(
            selectinload(DailyReport.author),
            selectinload(DailyReport.department),
            selectinload(DailyReport.recipients).selectinload(ReportRecipient.recipient),
        )
    )

    assert report is not None
    assert report.author.id == author.id
    assert report.department.id == department.id
    assert [r.recipient.id for r in report.recipients] == [manager.id]


async def test_relationships_are_never_lazy_loaded(db_session: AsyncSession) -> None:
    """Quên selectinload thì báo lỗi ngay, thay vì âm thầm chạy thêm query (N+1)."""
    user = await create_user(db_session)
    db_session.expunge_all()
    loaded = await db_session.get(User, user.id)
    assert loaded is not None

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = loaded.reports


async def test_one_report_per_author_per_day(db_session: AsyncSession) -> None:
    department = await create_department(db_session)
    author = await create_user(db_session, department=department)
    await create_report(db_session, author=author, department=department, report_date=TODAY)

    with pytest.raises(IntegrityError, match=REPORT_AUTHOR_DATE_UNIQUE):
        async with db_session.begin_nested():
            await create_report(db_session, author=author, department=department, report_date=TODAY)

    await create_report(
        db_session, author=author, department=department, report_date=TODAY - timedelta(days=1)
    )


async def test_deleting_report_removes_its_recipients(db_session: AsyncSession) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    author = await create_user(db_session, department=department)
    report = await create_report(
        db_session, author=author, department=department, report_date=TODAY, recipients=[manager]
    )

    await db_session.execute(delete(DailyReport).where(DailyReport.id == report.id))

    remaining = await db_session.scalars(
        select(ReportRecipient).where(ReportRecipient.report_id == report.id)
    )
    assert remaining.all() == []


@pytest.mark.parametrize("target", ["author", "recipient", "department"])
async def test_hard_delete_is_blocked_while_reports_reference_it(
    db_session: AsyncSession, target: str
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    author = await create_user(db_session, department=department)
    await create_report(
        db_session, author=author, department=department, report_date=TODAY, recipients=[manager]
    )
    statement = {
        "author": delete(User).where(User.id == author.id),
        "recipient": delete(User).where(User.id == manager.id),
        "department": delete(Department).where(Department.id == department.id),
    }[target]

    with pytest.raises(IntegrityError, match="violates foreign key constraint"):
        async with db_session.begin_nested():
            await db_session.execute(statement)


async def test_hard_deleting_department_detaches_members_and_managers(
    db_session: AsyncSession,
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    member = await create_user(db_session, department=department)

    await db_session.execute(delete(Department).where(Department.id == department.id))

    assert await db_session.scalar(select(User.department_id).where(User.id == member.id)) is None
    links = await db_session.scalar(
        text("SELECT count(*) FROM department_managers WHERE user_id = :id"), {"id": manager.id}
    )
    assert links == 0


async def test_hard_deleting_user_removes_tokens(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    expires = datetime.now(UTC) + timedelta(days=1)
    db_session.add_all(
        [
            RefreshToken(user_id=user.id, jti="jti-1", expires_at=expires),
            UserToken(
                user_id=user.id,
                token_hash="a" * 64,
                purpose=UserTokenPurpose.SETUP_PASSWORD,
                expires_at=expires,
            ),
        ]
    )
    await db_session.flush()

    await db_session.execute(delete(User).where(User.id == user.id))

    for model in (RefreshToken, UserToken):
        remaining = await db_session.scalars(select(model.id).where(model.user_id == user.id))
        assert remaining.all() == []


@pytest.mark.parametrize("duplicate_code", ["HR", "hr"])
async def test_department_code_is_unique_among_active_departments_only(
    db_session: AsyncSession, duplicate_code: str
) -> None:
    await create_department(db_session, code="HR", deleted=True)
    await create_department(db_session, code="HR")

    with pytest.raises(IntegrityError, match=DEPARTMENT_CODE_UNIQUE_INDEX):
        async with db_session.begin_nested():
            await create_department(db_session, code=duplicate_code)


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        (
            "INSERT INTO user_tokens (user_id, token_hash, purpose, expires_at) "
            "VALUES (:user_id, 'x', 'RESET_EVERYTHING', now())",
            "ck_user_tokens_user_token_purpose",
        ),
        (
            "INSERT INTO email_logs (to_email, template, status) "
            "VALUES ('a@example.com', 'report_created', 'QUEUED')",
            "ck_email_logs_email_status",
        ),
    ],
)
async def test_fixed_value_columns_reject_unknown_values(
    db_session: AsyncSession, sql: str, constraint: str
) -> None:
    user = await create_user(db_session)

    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.execute(text(sql), {"user_id": user.id})


async def test_email_dedup_key_prevents_sending_twice(db_session: AsyncSession) -> None:
    def log() -> EmailLog:
        return EmailLog(
            to_email="manager@example.com",
            template="monthly_summary",
            dedup_key="monthly:2026-10:dept:1:user:1",
            status=EmailStatus.SENT,
        )

    db_session.add(log())
    await db_session.flush()

    with pytest.raises(IntegrityError, match="uq_email_logs_dedup_key"):
        async with db_session.begin_nested():
            db_session.add(log())
