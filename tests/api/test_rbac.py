"""Phân quyền theo role: require_roles và nhóm router /admin, /manager.

Hai nhóm chưa có endpoint (Ngày 4, 6), nên test gắn route thăm dò vào app với đúng dependency
và response lỗi của nhóm, giống cách nhóm áp dụng cho route của module khi include.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, Depends, status
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.v1 import admin_router, manager_router
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError
from app.modules.users.models import UserRole
from tests.factories import auth_headers, create_user

API = get_settings().api_v1_prefix
# Role được phép của từng nhóm router.
GROUPS = {UserRole.ADMIN: admin_router, UserRole.MANAGER: manager_router}
WRONG_ROLES = [(group, role) for group in GROUPS for role in UserRole if role != group]
REPORTING_PREFIX = "/reporting"

probe_router = APIRouter()


# Route không tự kiểm tra gì: mọi lỗi 401, 403 đến từ dependency của nhóm.
@probe_router.get("/probe", status_code=status.HTTP_204_NO_CONTENT)
async def probe() -> None:
    pass


def probe_url(prefix: str) -> str:
    return f"{API}{prefix}/probe"


@pytest.fixture
async def probe_client(db_session: AsyncSession, redis: Redis) -> AsyncIterator[AsyncClient]:
    from app.core.database import get_db_session  # noqa: PLC0415 (xem docstring của conftest)
    from app.main import create_app  # noqa: PLC0415

    probe_app = create_app()
    for group in GROUPS.values():
        probe_app.include_router(
            probe_router,
            prefix=f"{API}{group.prefix}",
            dependencies=group.dependencies,
            responses=group.responses,
        )
    probe_app.include_router(
        probe_router,
        prefix=f"{API}{REPORTING_PREFIX}",
        dependencies=[Depends(require_roles(UserRole.USER, UserRole.MANAGER))],
    )
    probe_app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=probe_app), base_url="http://test") as http:
        yield http


@pytest.mark.parametrize("group", GROUPS)
async def test_group_requires_token(probe_client: AsyncClient, group: UserRole) -> None:
    response = await probe_client.get(probe_url(GROUPS[group].prefix))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("group", GROUPS)
async def test_group_rejects_locked_user_as_unauthorized(
    probe_client: AsyncClient, db_session: AsyncSession, group: UserRole
) -> None:
    # Tài khoản bị khóa là lỗi xác thực (401), không phải sai role, kể cả khi role đúng.
    user = await create_user(db_session, role=group, is_active=False)

    response = await probe_client.get(probe_url(GROUPS[group].prefix), headers=auth_headers(user))

    assert response.status_code == 401


@pytest.mark.parametrize(("group", "role"), WRONG_ROLES)
async def test_group_rejects_wrong_role_with_forbidden_error(
    probe_client: AsyncClient, db_session: AsyncSession, group: UserRole, role: UserRole
) -> None:
    user = await create_user(db_session, role=role)

    response = await probe_client.get(probe_url(GROUPS[group].prefix), headers=auth_headers(user))

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "FORBIDDEN", "message": ForbiddenError.message, "details": None}
    }


@pytest.mark.parametrize("group", GROUPS)
async def test_group_allows_its_role(
    probe_client: AsyncClient, db_session: AsyncSession, group: UserRole
) -> None:
    user = await create_user(db_session, role=group)

    response = await probe_client.get(probe_url(GROUPS[group].prefix), headers=auth_headers(user))

    assert response.status_code == 204


async def test_role_change_applies_to_issued_token(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    headers = auth_headers(manager)
    manager.role = UserRole.USER
    await db_session.flush()

    response = await probe_client.get(probe_url(manager_router.prefix), headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [(UserRole.USER, 204), (UserRole.MANAGER, 204), (UserRole.ADMIN, 403)],
)
async def test_require_roles_allows_any_listed_role(
    probe_client: AsyncClient, db_session: AsyncSession, role: UserRole, expected_status: int
) -> None:
    user = await create_user(db_session, role=role)

    response = await probe_client.get(probe_url(REPORTING_PREFIX), headers=auth_headers(user))

    assert response.status_code == expected_status


@pytest.mark.parametrize("group", GROUPS)
async def test_group_documents_auth_errors_in_swagger(
    probe_client: AsyncClient, group: UserRole
) -> None:
    response = await probe_client.get("/openapi.json")

    responses = response.json()["paths"][probe_url(GROUPS[group].prefix)]["get"]["responses"]
    for status_code in ("401", "403"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
