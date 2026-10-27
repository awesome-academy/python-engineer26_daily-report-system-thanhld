"""Lệnh `daily-report seed`: dữ liệu mẫu để demo và test thủ công.

Chỉ thêm những gì còn thiếu, nên chạy lại nhiều lần (kể cả các ngày sau) không tạo trùng.
"""

import asyncio
import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli._db import cli_session
from app.core.config import get_settings
from app.core.constants import Environment
from app.core.database import Base
from app.core.security import hash_password
from app.modules.departments.models import Department, DepartmentManager
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import Password


@dataclass(frozen=True)
class SeedDepartment:
    code: str
    name: str
    description: str


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: UserRole
    department_code: str | None


DEPARTMENTS = (
    SeedDepartment("DEV", "Phòng Phát triển", "Phát triển sản phẩm"),
    SeedDepartment("QA", "Phòng Kiểm thử", "Kiểm thử và đảm bảo chất lượng"),
    SeedDepartment("HR", "Phòng Nhân sự", "Tuyển dụng và đào tạo"),
)

# Nguồn duy nhất: manager của bộ phận suy ra từ user role MANAGER có department_code tương ứng.
USERS = (
    SeedUser("admin@example.com", "Quản trị viên", UserRole.ADMIN, None),
    SeedUser("manager.dev@example.com", "Trần Minh Quân", UserRole.MANAGER, "DEV"),
    SeedUser("manager.qa@example.com", "Lê Thu Hà", UserRole.MANAGER, "QA"),
    SeedUser("manager.hr@example.com", "Phạm Ngọc Lan", UserRole.MANAGER, "HR"),
    SeedUser("an.nguyen@example.com", "Nguyễn Văn An", UserRole.USER, "DEV"),
    SeedUser("binh.tran@example.com", "Trần Thị Bình", UserRole.USER, "DEV"),
    SeedUser("cuong.le@example.com", "Lê Quốc Cường", UserRole.USER, "QA"),
    SeedUser("dung.pham@example.com", "Phạm Thùy Dung", UserRole.USER, "QA"),
    SeedUser("giang.vo@example.com", "Võ Hoàng Giang", UserRole.USER, "HR"),
)

# Số ngày làm việc gần nhất (trước hôm nay) có báo cáo mẫu.
REPORT_DAYS = 5

# (việc dự định, việc thực tế đã làm, lý do chưa hoàn thành, việc ngày tiếp theo)
SAMPLE_WORK = (
    ("Làm API đăng nhập", "Xong API đăng nhập, viết test", None, "Làm API hồ sơ cá nhân"),
    (
        "Làm API hồ sơ cá nhân",
        "Xong xem, sửa hồ sơ",
        "Đổi mật khẩu chờ chốt quy tắc",
        "Đổi mật khẩu",
    ),
    ("Viết test phân quyền", "Xong test cho nhóm /admin", None, "Test cho nhóm /manager"),
    (
        "Sửa lỗi sau review",
        "Sửa 3/4 góp ý",
        "Một góp ý cần hỏi lại mentor",
        "Hoàn thành góp ý còn lại",
    ),
    ("Tối ưu truy vấn báo cáo", "Thêm index, bỏ N+1", None, "Export Excel báo cáo"),
)


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


def working_days_before(today: date, count: int) -> list[date]:
    """`count` ngày thứ 2 đến thứ 6 gần nhất trước `today`, sắp từ cũ đến mới."""
    days: list[date] = []
    day = today
    while len(days) < count:
        day -= timedelta(days=1)
        if day.weekday() <= calendar.FRIDAY:
            days.append(day)
    return sorted(days)


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
    session: AsyncSession, departments: dict[str, Department], password: str, result: SeedResult
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
    days = working_days_before(today, REPORT_DAYS)
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
        for offset, day in enumerate(days):
            if (author.id, day) in existing:
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
    users = await _ensure_users(session, departments, password, result)
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
        typer.secho(f"password: {exc.errors()[0]['msg']}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if reset and not yes:
        typer.confirm("Xóa TOÀN BỘ dữ liệu hiện có rồi seed lại?", abort=True)

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    result = asyncio.run(_run(password=password, today=today, reset=reset))

    typer.secho(
        f"Đã seed: {result.departments} bộ phận, {result.users} user, "
        f"{result.managers} lượt gán manager, {result.reports} báo cáo.",
        fg=typer.colors.GREEN,
    )
    for message in result.skipped:
        typer.secho(f"Bỏ qua {message}.", fg=typer.colors.YELLOW, err=True)
    if result.total == 0:
        typer.echo("Dữ liệu mẫu đã đủ, không tạo thêm gì.")
    typer.echo("Đăng nhập thử: manager.dev@example.com, an.nguyen@example.com (mật khẩu vừa nhập).")
