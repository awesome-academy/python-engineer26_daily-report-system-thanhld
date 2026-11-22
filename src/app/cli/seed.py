"""Lệnh `daily-report seed`: dữ liệu mẫu để demo và test thủ công.

Chỉ thêm những gì còn thiếu, nên chạy lại nhiều lần (kể cả các ngày sau) không tạo trùng.

Tài khoản mẫu coi như có từ ngày đầu tháng trước, báo cáo mẫu cho các ngày làm việc từ đó đến hôm
qua: dữ liệu theo đúng quy tắc của API (không có báo cáo trước ngày tạo tài khoản), và có sẵn tháng
trước để thử thống kê tháng (S3), export (M5) những ngày có người chưa nộp.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Annotated

import typer
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli._db import cli_session, exit_with_validation_errors
from app.core.clock import local_date, local_day_start, local_today
from app.core.config import get_settings
from app.core.constants import Environment
from app.core.database import Base
from app.core.security import hash_password
from app.core.workdays import is_working_day
from app.modules.departments.models import Department, DepartmentManager
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.reports.monthly_summary import previous_month
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import Password
from app.seed_data import DEPARTMENTS, EXAMPLE_EMPLOYEE, EXAMPLE_MANAGER, SAMPLE_WORK, USERS

# Mỗi nhân viên không nộp một trong mỗi chừng này ngày (lệch nhau giữa các nhân viên), để export,
# thống kê tháng có người chưa nộp.
MISSED_REPORT_EVERY = 5


@dataclass
class SeedResult:
    departments: int = 0
    users: int = 0
    managers: int = 0
    reports: int = 0
    # Tài khoản có sẵn không dùng được (sai role, bị khóa, chưa có bộ phận), kèm lý do.
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.departments + self.users + self.managers + self.reports


def history_start(today: date) -> date:
    """Ngày bắt đầu dữ liệu mẫu: ngày đầu tháng trước, tài khoản mẫu tạo mới coi như có từ đó."""
    return previous_month(today)


def report_days(today: date) -> list[date]:
    """Ngày làm việc từ `history_start` đến hôm qua, sắp từ cũ đến mới.

    Không có hôm nay, để thử tạo báo cáo.
    """
    start = history_start(today)
    days = (start + timedelta(days=n) for n in range((today - start).days))
    return [day for day in days if is_working_day(day)]


def is_missed(day: date, author_index: int) -> bool:
    """Ngày nhân viên thứ `author_index` không nộp. Tính theo ngày, nên seed lại hôm sau vẫn vậy."""
    return (day.toordinal() + author_index) % MISSED_REPORT_EVERY == 0


async def reset_data(session: AsyncSession) -> None:
    """Xóa toàn bộ dữ liệu nghiệp vụ, giữ schema và lịch sử migration."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


async def _ensure_departments(session: AsyncSession, result: SeedResult) -> dict[str, Department]:
    codes = [d.code for d in DEPARTMENTS]
    existing = {
        d.code: d
        for d in await session.scalars(
            select(Department).where(Department.code.in_(codes), Department.deleted_at.is_(None))
        )
    }
    for item in DEPARTMENTS:
        if item.code not in existing:
            existing[item.code] = Department(
                code=item.code, name=item.name, description=item.description
            )
            session.add(existing[item.code])
            result.departments += 1
    await session.flush()
    return existing


async def _ensure_users(
    session: AsyncSession,
    departments: dict[str, Department],
    *,
    password: str,
    today: date,
    result: SeedResult,
) -> dict[str, User]:
    emails = [u.email for u in USERS]
    existing = {
        u.email.lower(): u
        for u in await session.scalars(
            select(User).where(func.lower(User.email).in_(emails), User.deleted_at.is_(None))
        )
    }
    missing = [u for u in USERS if u.email not in existing]
    if missing:
        password_hash = await hash_password(password)
        for item in missing:
            department = departments.get(item.department_code or "")
            existing[item.email] = User(
                email=item.email,
                full_name=item.full_name,
                role=item.role,
                department_id=department.id if department else None,
                password_hash=password_hash,
                created_at=local_day_start(history_start(today)),
            )
            session.add(existing[item.email])
        result.users += len(missing)
    await session.flush()
    return existing


def _cannot_act_as(user: User, role: UserRole) -> str | None:
    """Lý do tài khoản (có thể đã có sẵn trong DB) không dùng được với vai trò `role`."""
    if not user.is_active:
        return "tài khoản bị khóa"
    if user.role is not role:
        return f"role {user.role.value}, không phải {role.value}"
    return None


async def _ensure_managers(
    session: AsyncSession,
    departments: dict[str, Department],
    users: dict[str, User],
    result: SeedResult,
) -> None:
    rows = await session.execute(select(DepartmentManager.department_id, DepartmentManager.user_id))
    linked = {tuple(row) for row in rows}
    for item in USERS:
        if item.role is not UserRole.MANAGER or not item.department_code:
            continue
        user = users[item.email]
        # Theo A3, chỉ gán user role MANAGER: xét role thật trong DB, không theo USERS.
        if reason := _cannot_act_as(user, UserRole.MANAGER):
            result.skipped.append(
                f"{user.email}: {reason}, không gán làm manager {item.department_code}"
            )
            continue
        department_id = departments[item.department_code].id
        if (department_id, user.id) not in linked:
            session.add(DepartmentManager(department_id=department_id, user_id=user.id))
            result.managers += 1
    await session.flush()


def _report_authors(users: dict[str, User], result: SeedResult) -> list[tuple[User, int]]:
    """Nhân viên viết được báo cáo (Q3: chỉ role USER), kèm bộ phận thật của họ."""
    authors: list[tuple[User, int]] = []
    for item in USERS:
        if item.role is not UserRole.USER:
            continue
        user = users[item.email]
        reason = _cannot_act_as(user, UserRole.USER)
        if reason is None and user.department_id is not None:
            authors.append((user, user.department_id))
        else:
            reason = reason or "chưa thuộc bộ phận nào"
            result.skipped.append(f"{user.email}: {reason}, không tạo báo cáo mẫu")
    return authors


async def _active_managers(session: AsyncSession, department_ids: set[int]) -> dict[int, list[int]]:
    """Id manager đang hoạt động của từng bộ phận, đọc từ DB."""
    rows = await session.execute(
        select(DepartmentManager.department_id, DepartmentManager.user_id)
        .join(User, User.id == DepartmentManager.user_id)
        .where(
            DepartmentManager.department_id.in_(department_ids),
            User.is_active,
            User.deleted_at.is_(None),
        )
    )
    managers: dict[int, list[int]] = defaultdict(list)
    for department_id, user_id in rows:
        managers[department_id].append(user_id)
    return managers


async def _ensure_reports(
    session: AsyncSession, *, users: dict[str, User], today: date, result: SeedResult
) -> None:
    authors = _report_authors(users, result)
    if not authors:
        return
    days = report_days(today)
    # Bộ phận và người nhận theo dữ liệu thật của author, vì tài khoản có thể đã có sẵn.
    managers = await _active_managers(session, {department_id for _, department_id in authors})
    pairs = [(author.id, day) for author, _ in authors for day in days]
    rows = await session.execute(
        select(DailyReport.author_id, DailyReport.report_date).where(
            tuple_(DailyReport.author_id, DailyReport.report_date).in_(pairs)
        )
    )
    existing = {tuple(row) for row in rows}
    for index, (author, department_id) in enumerate(authors):
        # Tài khoản có sẵn có thể tạo sau ngày đầu dữ liệu mẫu: API không nhận báo cáo cho ngày
        # trước khi có tài khoản, seed cũng vậy.
        first_day = local_date(author.created_at)
        for offset, day in enumerate(days):
            if day < first_day or is_missed(day, index) or (author.id, day) in existing:
                continue
            planned, actual, reason, next_day = SAMPLE_WORK[(index + offset) % len(SAMPLE_WORK)]
            report = DailyReport(
                author_id=author.id,
                department_id=department_id,
                report_date=day,
                planned_work=planned,
                actual_work=actual,
                incomplete_reason=reason,
                next_day_plan=next_day,
            )
            report.recipients = [ReportRecipient(recipient_id=m) for m in managers[department_id]]
            session.add(report)
            result.reports += 1
    await session.flush()


async def seed_data(session: AsyncSession, *, password: str, today: date) -> SeedResult:
    """Thêm dữ liệu mẫu còn thiếu. Không commit; caller quyết định transaction."""
    result = SeedResult()
    departments = await _ensure_departments(session, result)
    users = await _ensure_users(session, departments, password=password, today=today, result=result)
    await _ensure_managers(session, departments, users, result)
    await _ensure_reports(session, users=users, today=today, result=result)
    return result


async def _run(*, password: str, today: date, reset: bool) -> SeedResult:
    async with cli_session() as session:
        if reset:
            await reset_data(session)
        result = await seed_data(session, password=password, today=today)
        await session.commit()
        return result


def seed(
    password: Annotated[
        str,
        typer.Option(
            prompt="Mật khẩu cho các tài khoản mẫu",
            hide_input=True,
            envvar="SEED_USER_PASSWORD",
            help="Mật khẩu chung cho tài khoản mẫu tạo mới. Bỏ trống để nhập ẩn.",
        ),
    ],
    reset: Annotated[
        bool, typer.Option("--reset", help="Xóa toàn bộ dữ liệu trước khi seed")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Không hỏi xác nhận khi --reset")
    ] = False,
) -> None:
    """Tạo dữ liệu mẫu: bộ phận, admin, manager, nhân viên, báo cáo các ngày gần nhất."""
    settings = get_settings()
    if settings.environment is Environment.PRODUCTION:
        typer.secho("Không chạy seed trên môi trường production.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        TypeAdapter(Password).validate_python(password)
    except ValidationError as exc:
        raise exit_with_validation_errors(exc, field="password") from exc
    if reset and not yes:
        typer.confirm("Xóa TOÀN BỘ dữ liệu hiện có rồi seed lại?", abort=True)

    result = asyncio.run(_run(password=password, today=local_today(), reset=reset))

    typer.secho(
        f"Đã seed: {result.departments} bộ phận, {result.users} user, "
        f"{result.managers} lượt gán manager, {result.reports} báo cáo.",
        fg=typer.colors.GREEN,
    )
    for message in result.skipped:
        typer.secho(f"Bỏ qua {message}.", fg=typer.colors.YELLOW, err=True)
    if result.total == 0:
        typer.echo("Dữ liệu mẫu đã đủ, không tạo thêm gì.")
    typer.echo(
        f"Đăng nhập thử: {EXAMPLE_MANAGER.email}, {EXAMPLE_EMPLOYEE.email} (mật khẩu vừa nhập)."
    )
