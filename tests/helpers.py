"""Helper dùng chung cho test."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner, Result

from app.cli import cli
from app.core.config import get_settings
from app.core.constants import BIGINT_MAX
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.exceptions import DepartmentNotFoundError
from app.modules.departments.models import Department
from app.modules.users.models import UserRole
from tests.factories import DEFAULT_PASSWORD, auth_headers, create_department, create_user

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"

runner = CliRunner()


async def invoke(*args: str) -> Result:
    # Lệnh CLI tự chạy asyncio.run(), nên phải chạy ở thread khác event loop của test.
    def run() -> Result:
        return runner.invoke(cli, list(args))

    return await asyncio.to_thread(run)


def make_token(user_id: int, **overrides: Any) -> str:
    """Ghép JWT bằng tay để thử token hết hạn, sai chữ ký, sai loại. Mặc định là access token."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": "USER",
        "ver": 0,
        "jti": "test",
        "sid": "test",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    settings = get_settings()
    secret = overrides.pop("secret", settings.jwt_secret_key)
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm=settings.jwt_algorithm)


async def login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post(LOGIN_URL, data={"username": email, "password": password})


async def login_tokens(client: AsyncClient, email: str) -> dict[str, str]:
    response = await login(client, email, DEFAULT_PASSWORD)
    assert response.status_code == 200
    tokens: dict[str, str] = response.json()
    return tokens


async def refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post(REFRESH_URL, json={"refresh_token": refresh_token})


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def error_json(error: AppError) -> dict[str, Any]:
    """Body JSON mà handler chung trả cho lỗi nghiệp vụ `error`."""
    return {"error": {"code": error.code, "message": error.message, "details": error.details}}


@dataclass(frozen=True)
class ScopeTarget:
    """Một dòng của ma trận quyền: header của người gọi và id bộ phận trên URL."""

    headers: dict[str, str]
    department_id: int


ArrangeScope = Callable[[AsyncSession], Awaitable[ScopeTarget]]


async def _department_with_manager(session: AsyncSession, *, deleted: bool = False) -> Department:
    # Bộ phận luôn có manager riêng, để dòng "ngoài phạm vi" không đúng chỉ vì bộ phận trống.
    manager = await create_user(session, role=UserRole.MANAGER)
    return await create_department(session, managers=[manager], deleted=deleted)


def _caller_with_role(role: UserRole | None) -> ArrangeScope:
    """Người gọi không dính gì tới bộ phận: chưa đăng nhập (`None`) hoặc chỉ có role."""

    async def arrange(session: AsyncSession) -> ScopeTarget:
        department = await _department_with_manager(session)
        if role is None:
            return ScopeTarget({}, department.id)
        return ScopeTarget(auth_headers(await create_user(session, role=role)), department.id)

    return arrange


async def _manager_of_other_department(session: AsyncSession) -> ScopeTarget:
    department = await _department_with_manager(session)
    manager = await create_user(session, role=UserRole.MANAGER)
    await create_department(session, managers=[manager])
    return ScopeTarget(auth_headers(manager), department.id)


async def _manager_member_not_assigned(session: AsyncSession) -> ScopeTarget:
    # Thuộc bộ phận (users.department_id) nhưng admin chưa gán làm manager.
    department = await _department_with_manager(session)
    manager = await create_user(session, role=UserRole.MANAGER, department=department)
    return ScopeTarget(auth_headers(manager), department.id)


async def _manager_of_deleted_department(session: AsyncSession) -> ScopeTarget:
    manager = await create_user(session, role=UserRole.MANAGER)
    department = await create_department(session, managers=[manager], deleted=True)
    return ScopeTarget(auth_headers(manager), department.id)


async def _missing_department(session: AsyncSession) -> ScopeTarget:
    manager = await create_user(session, role=UserRole.MANAGER)
    await create_department(session, managers=[manager])
    return ScopeTarget(auth_headers(manager), BIGINT_MAX)


def _assigned_caller(**user_fields: Any) -> ArrangeScope:
    """Người gọi có dòng `department_managers` của bộ phận, tài khoản theo `user_fields`.

    Mặc định là manager đang hoạt động. Khóa, hạ role, xóa mềm tài khoản không gỡ dòng liên kết,
    nên lớp kiểm tra token (401), role (403) phải chặn trước, không trông vào policy phạm vi.
    """

    async def arrange(session: AsyncSession) -> ScopeTarget:
        user = await create_user(session, **{"role": UserRole.MANAGER, **user_fields})
        department = await create_department(session, managers=[user])
        return ScopeTarget(auth_headers(user), department.id)

    return arrange


async def _one_of_several_managers(session: AsyncSession) -> ScopeTarget:
    first = await create_user(session, role=UserRole.MANAGER)
    second = await create_user(session, role=UserRole.MANAGER)
    department = await create_department(session, managers=[first, second])
    return ScopeTarget(auth_headers(second), department.id)


async def _manager_of_several_departments(session: AsyncSession) -> ScopeTarget:
    manager = await create_user(session, role=UserRole.MANAGER)
    await create_department(session, managers=[manager])
    department = await create_department(session, managers=[manager])
    return ScopeTarget(auth_headers(manager), department.id)


# Ma trận quyền của endpoint /manager có `{department_id}` trên URL, dùng với
# pytest.mark.parametrize cho từng endpoint của Ngày 6. Thứ tự lỗi: token (401) → role (403) →
# phạm vi (404). Ngoài phạm vi trả đúng body của bộ phận không tồn tại.
DEPARTMENT_SCOPE_DENIED = [
    pytest.param(_caller_with_role(None), UnauthorizedError(), id="anonymous"),
    pytest.param(_caller_with_role(UserRole.USER), ForbiddenError(), id="user"),
    pytest.param(_caller_with_role(UserRole.ADMIN), ForbiddenError(), id="admin"),
    pytest.param(_assigned_caller(is_active=False), UnauthorizedError(), id="assigned-but-locked"),
    pytest.param(_assigned_caller(deleted=True), UnauthorizedError(), id="assigned-but-deleted"),
    pytest.param(_assigned_caller(role=UserRole.USER), ForbiddenError(), id="assigned-but-demoted"),
    pytest.param(
        _caller_with_role(UserRole.MANAGER), DepartmentNotFoundError(), id="manager-no-department"
    ),
    pytest.param(
        _manager_of_other_department, DepartmentNotFoundError(), id="manager-other-department"
    ),
    pytest.param(
        _manager_member_not_assigned, DepartmentNotFoundError(), id="manager-member-not-assigned"
    ),
    pytest.param(
        _manager_of_deleted_department, DepartmentNotFoundError(), id="deleted-department"
    ),
    pytest.param(_missing_department, DepartmentNotFoundError(), id="missing-department"),
]
DEPARTMENT_SCOPE_ALLOWED = [
    pytest.param(_assigned_caller(), id="manager"),
    pytest.param(_one_of_several_managers, id="one-of-several-managers"),
    pytest.param(_manager_of_several_departments, id="manager-of-several-departments"),
]
