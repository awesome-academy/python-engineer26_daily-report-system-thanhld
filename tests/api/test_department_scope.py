"""Policy phạm vi bộ phận của manager (`ManagedDepartment`), chạy theo ma trận quyền.

Chưa có endpoint /manager nào (Ngày 6), nên test gắn route thăm dò dùng `ManagedDepartment` vào
app riêng, với đúng dependency và response lỗi của nhóm /manager, giống test_rbac.py. Endpoint
thật có `{department_id}` trên URL thêm vào SCOPED_ENDPOINTS để chạy cùng ma trận.
"""

import pytest
from fastapi import APIRouter, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import manager_router
from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, ID_MIN
from app.core.exceptions import AppError, UnauthorizedError
from app.modules.departments.dependencies import ManagedDepartment
from app.modules.departments.exceptions import DepartmentNotFoundError
from app.modules.departments.service import DepartmentService
from app.modules.users.models import UserRole
from tests.factories import auth_headers, create_department, create_user
from tests.helpers import (
    DEPARTMENT_SCOPE_ALLOWED,
    DEPARTMENT_SCOPE_DENIED,
    ArrangeScope,
    error_json,
)

API = get_settings().api_v1_prefix
PROBE_PATH = f"{manager_router.prefix}/scope-probe/{{department_id}}"
# Endpoint /manager có bộ phận trên URL: (method, đường dẫn sau tiền tố API).
SCOPED_ENDPOINTS = [pytest.param(("GET", PROBE_PATH), id="probe")]

probe_router = APIRouter()


@probe_router.get("/scope-probe/{department_id}")
async def scope_probe(department: ManagedDepartment) -> dict[str, int]:
    # Trả id để test thấy handler nhận đúng bản ghi bộ phận trên URL.
    return {"id": department.id}


@pytest.fixture(autouse=True)
def mount_probe_route(probe_app: FastAPI) -> None:
    probe_app.include_router(
        probe_router,
        prefix=f"{API}{manager_router.prefix}",
        dependencies=manager_router.dependencies,
        responses=manager_router.responses,
    )


def probe_url(department_id: int | str) -> str:
    return f"{API}{PROBE_PATH.format(department_id=department_id)}"


@pytest.mark.parametrize("endpoint", SCOPED_ENDPOINTS)
@pytest.mark.parametrize(("arrange", "error"), DEPARTMENT_SCOPE_DENIED)
async def test_scoped_endpoint_denies_caller_outside_scope(
    probe_client: AsyncClient,
    db_session: AsyncSession,
    endpoint: tuple[str, str],
    arrange: ArrangeScope,
    error: AppError,
) -> None:
    method, path = endpoint
    target = await arrange(db_session)

    response = await probe_client.request(
        method, f"{API}{path.format(department_id=target.department_id)}", headers=target.headers
    )

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


@pytest.mark.parametrize("arrange", DEPARTMENT_SCOPE_ALLOWED)
async def test_managed_department_passes_department_to_handler(
    probe_client: AsyncClient, db_session: AsyncSession, arrange: ArrangeScope
) -> None:
    target = await arrange(db_session)

    response = await probe_client.get(probe_url(target.department_id), headers=target.headers)

    assert response.status_code == 200
    assert response.json() == {"id": target.department_id}


async def test_manager_loses_access_once_removed_from_department(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Phạm vi đọc từ DB ở mỗi request: token cấp trước khi bị gỡ cũng không vào được nữa.
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    headers = auth_headers(manager)
    await DepartmentService(db_session).remove_manager(department.id, manager.id)

    response = await probe_client.get(probe_url(department.id), headers=headers)

    assert response.json() == error_json(DepartmentNotFoundError())


@pytest.mark.parametrize("department_id", [ID_MIN - 1, BIGINT_MAX + 1, "abc"])
async def test_managed_department_rejects_invalid_id(
    probe_client: AsyncClient, db_session: AsyncSession, department_id: int | str
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)

    response = await probe_client.get(probe_url(department_id), headers=auth_headers(manager))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "path.department_id"


async def test_token_is_checked_before_department_id(probe_client: AsyncClient) -> None:
    response = await probe_client.get(probe_url(ID_MIN - 1))

    assert response.json() == error_json(UnauthorizedError())
