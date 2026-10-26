"""Hàm tạo dữ liệu mẫu cho test."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from itertools import count

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.departments.models import Department
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole

DEFAULT_PASSWORD = "Matkhau@123"

_sequence = count(1)
# Băm Argon2 tốn thời gian, nên mỗi mật khẩu chỉ băm một lần cho cả bộ test.
_password_hashes: dict[str, str] = {}


async def create_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    full_name: str = "Nguyễn Văn An",
    password: str | None = DEFAULT_PASSWORD,
    role: UserRole = UserRole.USER,
    is_active: bool = True,
    deleted: bool = False,
    department: Department | None = None,
) -> User:
    password_hash = None
    if password is not None:
        if password not in _password_hashes:
            _password_hashes[password] = await hash_password(password)
        password_hash = _password_hashes[password]

    user = User(
        email=email or f"user{next(_sequence)}@example.com",
        full_name=full_name,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(UTC) if deleted else None,
        department_id=department.id if department else None,
    )
    session.add(user)
    await session.flush()
    return user


async def create_department(
    session: AsyncSession,
    *,
    code: str | None = None,
    name: str = "Phòng Kỹ thuật",
    managers: Sequence[User] = (),
    deleted: bool = False,
) -> Department:
    department = Department(
        code=code or f"D{next(_sequence):03d}",
        name=name,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    # Bộ phận mới chưa có gì để load, nên gán quan hệ trực tiếp không vi phạm lazy="raise".
    department.managers = list(managers)
    session.add(department)
    await session.flush()
    return department


async def create_report(
    session: AsyncSession,
    *,
    author: User,
    department: Department,
    report_date: date,
    recipients: Sequence[User] = (),
) -> DailyReport:
    report = DailyReport(
        author_id=author.id,
        department_id=department.id,
        report_date=report_date,
        planned_work="Làm API đăng nhập",
        actual_work="Xong API đăng nhập, viết test",
        next_day_plan="Làm API hồ sơ cá nhân",
    )
    report.recipients = [ReportRecipient(recipient_id=user.id) for user in recipients]
    session.add(report)
    await session.flush()
    return report


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role, token_version=user.token_version)
    return {"Authorization": f"Bearer {token.token}"}
