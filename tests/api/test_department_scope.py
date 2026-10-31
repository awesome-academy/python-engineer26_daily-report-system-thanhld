"""Policy phạm vi bộ phận của manager (`ManagedDepartment`), chạy theo ma trận quyền.

Mọi route dưới /manager/departments/{...} thao tác trên một bộ phận cụ thể, nên phải đi qua
`ManagedDepartment`. Danh sách route lấy từ app (route thật và route thăm dò), không liệt kê tay:
endpoint Ngày 6 thêm vào là tự chạy ma trận, và test đỏ nếu endpoint không dùng dependency.

Chưa có endpoint /manager nào, nên route thăm dò gắn vào app riêng với đúng dependency và
response lỗi của nhóm /manager, giống test_rbac.py.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router, manager_router
from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, ID_MIN
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError, error_responses
from app.core.validators import Id
from app.modules.departments.dependencies import ManagedDepartment, get_managed_department
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
SCOPED_PREFIX = f"{API}{manager_router.prefix}/departments/"
PATH_PARAM = re.compile(r"\{(\w+)\}")
_SCOPE_ERRORS = error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT)

probe_router = APIRouter(
    prefix=f"{API}{manager_router.prefix}",
    dependencies=manager_router.dependencies,
    responses=manager_router.responses,
)


class ProbeBody(BaseModel):
    user_id: Id


# Khai 404, 422 như mọi endpoint thật dùng ManagedDepartment phải khai.
@probe_router.get("/departments/{department_id}/scope-probe", responses=_SCOPE_ERRORS)
async def read_probe(department: ManagedDepartment) -> dict[str, int]:
    # Trả id để test thấy handler nhận đúng bản ghi bộ phận trên URL.
    return {"id": department.id}


# Endpoint ghi có body (như M2 thêm thành viên): phạm vi được kiểm tra trước body.
@probe_router.post("/departments/{department_id}/scope-probe", responses=_SCOPE_ERRORS)
async def write_probe(department: ManagedDepartment, data: ProbeBody) -> dict[str, int]:
    return {"id": department.id, "user_id": data.user_id}


def scoped_routes() -> list[APIRoute]:
    return [
        route
        for route in [*api_router.routes, *probe_router.routes]
        if isinstance(route, APIRoute) and route.path.startswith(SCOPED_PREFIX)
    ]


SCOPED_ENDPOINTS = [
    pytest.param((method, route.path), id=f"{method} {route.path.removeprefix(API)}")
    for route in scoped_routes()
    for method in sorted(route.methods or ())
]


def dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from dependency_calls(sub)


def fill_path(path: str, department_id: int | str) -> str:
    # Param khác trên URL (user_id) lấy id hợp lệ bất kỳ: lỗi phạm vi phải có trước khi xét nó.
    return PATH_PARAM.sub(
        lambda match: str(department_id if match[1] == "department_id" else ID_MIN), path
    )


def probe_url(department_id: int | str) -> str:
    return fill_path(f"{SCOPED_PREFIX}{{department_id}}/scope-probe", department_id)


@pytest.fixture(autouse=True)
def mount_probe_routes(probe_app: FastAPI) -> None:
    probe_app.include_router(probe_router)


@pytest.mark.parametrize("route", scoped_routes(), ids=lambda route: route.path)
def test_department_route_goes_through_managed_department(route: APIRoute) -> None:
    # ManagedDepartment đọc path param tên department_id: đặt tên khác ({id}) thì mọi request 422.
    assert "{department_id}" in route.path
    assert get_managed_department in set(dependency_calls(route.dependant))


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
        method, fill_path(path, target.department_id), headers=target.headers
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


async def test_body_is_validated_after_scope(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])

    response = await probe_client.post(probe_url(department.id), headers=auth_headers(manager))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body"


async def test_manager_loses_access_once_removed_from_department(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Phạm vi đọc từ DB ở mỗi request: token cấp trước khi bị gỡ cũng không vào được nữa.
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    headers = auth_headers(manager)
    await DepartmentService(db_session).remove_manager(department.id, manager.id)

    response = await probe_client.get(probe_url(department.id), headers=headers)

    assert response.status_code == 404
    assert response.json() == error_json(DepartmentNotFoundError())


@pytest.mark.parametrize("department_id", [ID_MIN - 1, BIGINT_MAX + 1, "abc"])
async def test_managed_department_rejects_invalid_id(
    probe_client: AsyncClient, db_session: AsyncSession, department_id: int | str
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)

    response = await probe_client.get(probe_url(department_id), headers=auth_headers(manager))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "path.department_id"


@pytest.mark.parametrize(
    ("role", "error"),
    [(None, UnauthorizedError()), (UserRole.USER, ForbiddenError())],
    ids=["anonymous", "user"],
)
async def test_token_and_role_are_checked_before_department_id(
    probe_client: AsyncClient, db_session: AsyncSession, role: UserRole | None, error: AppError
) -> None:
    headers = auth_headers(await create_user(db_session, role=role)) if role else {}

    response = await probe_client.get(probe_url(ID_MIN - 1), headers=headers)

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


@pytest.mark.parametrize("endpoint", SCOPED_ENDPOINTS)
async def test_scoped_endpoint_documents_scope_errors_in_swagger(
    probe_client: AsyncClient, endpoint: tuple[str, str]
) -> None:
    # Dependency không tự khai response trên Swagger: endpoint quên khai 404, 422 thì đỏ.
    method, path = endpoint
    paths = (await probe_client.get("/openapi.json")).json()["paths"]

    responses = paths[path][method.lower()]["responses"]
    for status_code in ("404", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
