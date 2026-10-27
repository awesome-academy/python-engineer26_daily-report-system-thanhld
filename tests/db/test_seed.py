from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from app.cli import seed as seed_module
from app.cli.seed import (
    DEPARTMENTS,
    REPORT_DAYS,
    USERS,
    reset_data,
    seed_data,
    working_days_before,
)
from app.core.config import Settings
from app.core.constants import Environment
from app.core.database import Base
from app.core.security import verify_password
from app.modules.departments.models import Department
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole
from tests.factories import create_department, create_user
from tests.helpers import invoke

SEED_PASSWORD = "Matkhau@123"
MONDAY = date(2026, 10, 26)
EMPLOYEES = [u for u in USERS if u.role is UserRole.USER]


async def count(session: AsyncSession, model: type[Base]) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


def test_working_days_skip_weekends() -> None:
    assert working_days_before(MONDAY, 3) == [
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    ]


async def test_seed_creates_sample_data(db_session: AsyncSession) -> None:
    result = await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    assert (result.departments, result.users, result.managers, result.reports) == (
        len(DEPARTMENTS),
        len(USERS),
        len(DEPARTMENTS),
        len(EMPLOYEES) * REPORT_DAYS,
    )
    assert await count(db_session, DailyReport) == len(EMPLOYEES) * REPORT_DAYS


async def test_seeded_accounts_can_log_in_with_given_password(db_session: AsyncSession) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    user = await db_session.scalar(select(User).where(User.email == "an.nguyen@example.com"))

    assert user is not None
    assert user.password_hash is not None
    assert await verify_password(SEED_PASSWORD, user.password_hash)


async def test_managers_come_from_manager_users_of_each_department(
    db_session: AsyncSession,
) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    departments = await db_session.scalars(
        select(Department).options(selectinload(Department.managers))
    )

    for department in departments:
        expected = {
            u.email
            for u in USERS
            if u.role is UserRole.MANAGER and u.department_code == department.code
        }
        assert {m.email for m in department.managers} == expected


async def test_report_recipients_are_managers_of_author_department(
    db_session: AsyncSession,
) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    reports = await db_session.scalars(
        select(DailyReport).options(
            selectinload(DailyReport.author),
            selectinload(DailyReport.department).selectinload(Department.managers),
            selectinload(DailyReport.recipients).selectinload(ReportRecipient.recipient),
        )
    )

    for report in reports:
        assert report.author.department_id == report.department_id
        assert {r.recipient.id for r in report.recipients} == {
            m.id for m in report.department.managers
        }
        assert report.report_date < MONDAY
        assert report.report_date.weekday() < 5


async def test_seed_again_creates_nothing(db_session: AsyncSession) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    result = await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    assert result.total == 0


async def test_seed_next_day_only_adds_new_reports(db_session: AsyncSession) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    result = await seed_data(db_session, password=SEED_PASSWORD, today=date(2026, 10, 27))

    assert (result.departments, result.users, result.managers) == (0, 0, 0)
    assert result.reports == len(EMPLOYEES)


async def test_seed_keeps_existing_accounts_unchanged(db_session: AsyncSession) -> None:
    await create_user(
        db_session, email="admin@example.com", full_name="Admin của tôi", role=UserRole.ADMIN
    )

    result = await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    admin = await db_session.scalar(select(User).where(User.email == "admin@example.com"))
    assert admin is not None
    assert admin.full_name == "Admin của tôi"
    assert result.users == len(USERS) - 1


@pytest.mark.parametrize(("role", "is_active"), [(UserRole.USER, True), (UserRole.MANAGER, False)])
async def test_seed_skips_existing_account_that_cannot_be_manager(
    db_session: AsyncSession, role: UserRole, is_active: bool
) -> None:
    await create_user(db_session, email="manager.dev@example.com", role=role, is_active=is_active)

    result = await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    dev = await db_session.scalar(
        select(Department)
        .where(Department.code == "DEV")
        .options(selectinload(Department.managers))
    )
    assert dev is not None
    assert dev.managers == []
    assert result.managers == len(DEPARTMENTS) - 1
    assert any("manager.dev@example.com" in message for message in result.skipped)


@pytest.mark.parametrize(
    ("role", "is_active", "has_department"),
    [
        (UserRole.USER, False, True),
        (UserRole.USER, True, False),
        (UserRole.MANAGER, True, True),
    ],
)
async def test_seed_skips_reports_of_existing_account_that_cannot_write_reports(
    db_session: AsyncSession, role: UserRole, is_active: bool, has_department: bool
) -> None:
    department = await create_department(db_session, code="OPS") if has_department else None
    author = await create_user(
        db_session,
        email="an.nguyen@example.com",
        role=role,
        is_active=is_active,
        department=department,
    )

    result = await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    reports = await db_session.scalar(
        select(func.count()).select_from(DailyReport).where(DailyReport.author_id == author.id)
    )
    assert reports == 0
    assert result.reports == (len(EMPLOYEES) - 1) * REPORT_DAYS
    assert any("an.nguyen@example.com" in message for message in result.skipped)


async def test_seed_reports_follow_author_actual_department(db_session: AsyncSession) -> None:
    ops_manager = await create_user(db_session, role=UserRole.MANAGER)
    ops = await create_department(db_session, code="OPS", managers=[ops_manager])
    author = await create_user(db_session, email="an.nguyen@example.com", department=ops)

    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    reports = (
        await db_session.scalars(
            select(DailyReport)
            .where(DailyReport.author_id == author.id)
            .options(selectinload(DailyReport.recipients))
        )
    ).all()
    assert len(reports) == REPORT_DAYS
    for report in reports:
        assert report.department_id == ops.id
        assert [r.recipient_id for r in report.recipients] == [ops_manager.id]


async def test_reset_clears_all_data(db_session: AsyncSession) -> None:
    await seed_data(db_session, password=SEED_PASSWORD, today=MONDAY)

    await reset_data(db_session)

    assert await count(db_session, User) == 0
    assert await count(db_session, DailyReport) == 0


@pytest.fixture
async def clean_after(engine: AsyncEngine) -> AsyncIterator[None]:
    """Lệnh CLI commit thật vào DB test, nên xóa sạch dữ liệu sau test."""
    yield
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.mark.usefixtures("clean_after")
async def test_seed_command_runs_twice_without_duplicates() -> None:
    first = await invoke("seed", "--password", SEED_PASSWORD)
    second = await invoke("seed", "--password", SEED_PASSWORD, "--reset", "--yes")
    third = await invoke("seed", "--password", SEED_PASSWORD)

    assert first.exit_code == 0, first.output
    assert f"{len(USERS)} user" in first.output
    assert second.exit_code == 0, second.output
    assert f"{len(USERS)} user" in second.output
    assert "không tạo thêm gì" in third.output


@pytest.mark.usefixtures("clean_after")
async def test_seed_command_warns_about_skipped_accounts(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session:
        await create_user(session, email="an.nguyen@example.com", is_active=False)
        await session.commit()

    result = await invoke("seed", "--password", SEED_PASSWORD)

    assert result.exit_code == 0, result.output
    assert "Bỏ qua an.nguyen@example.com: tài khoản bị khóa" in result.output


async def test_seed_command_rejects_short_password() -> None:
    result = await invoke("seed", "--password", "ngan")

    assert result.exit_code == 1
    assert "password:" in result.output


async def test_seed_command_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    production = Settings(environment=Environment.PRODUCTION, jwt_secret_key="s" * 48)
    monkeypatch.setattr(seed_module, "get_settings", lambda: production)

    result = await invoke("seed", "--password", SEED_PASSWORD)

    assert result.exit_code == 2
    assert "production" in result.output
