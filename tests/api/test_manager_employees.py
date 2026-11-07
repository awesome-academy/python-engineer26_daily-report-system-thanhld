from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, ID_MIN, KEYWORD_MAX_LENGTH, MAX_PAGE_SIZE
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.models import Department
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user
from tests.helpers import error_json

API = get_settings().api_v1_prefix
EMPLOYEES_URL = f"{API}/manager/employees"
EMPLOYEE_FIELDS = {
    "id",
    "email",
    "full_name",
    "phone",
    "date_of_birth",
    "role",
    "is_active",
    "last_login_at",
    "created_at",
    "department_id",
}


def employee_url(user_id: int | str) -> str:
    return f"{EMPLOYEES_URL}/{user_id}"


def listed_ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["data"]]


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, full_name="Quản Lý", role=UserRole.MANAGER)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, managers=[manager])


@pytest.fixture
def headers(manager: User) -> dict[str, str]:
    return auth_headers(manager)


# Danh sách


async def test_manager_lists_employees_of_every_managed_department(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    department: Department,
    headers: dict[str, str],
) -> None:
    second = await create_department(db_session, managers=[manager])
    an = await create_user(db_session, full_name="Lê Văn An", department=department)
    binh = await create_user(db_session, full_name="Bùi Thị Bình", department=second)
    # Tài khoản bị khóa vẫn là nhân viên: manager còn xem báo cáo cũ của họ.
    cuong = await create_user(
        db_session, full_name="Trần Văn Cường", is_active=False, department=department
    )
    await create_user(db_session, full_name="Đã Xóa", deleted=True, department=department)

    response = await client.get(EMPLOYEES_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 3}
    assert [(e["id"], e["department_id"], e["is_active"]) for e in body["data"]] == [
        (binh.id, second.id, True),
        (an.id, department.id, True),
        (cuong.id, department.id, False),
    ]
    assert set(body["data"][0]) == EMPLOYEE_FIELDS


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
async def test_manager_does_not_list_members_with_other_roles(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    role: UserRole,
) -> None:
    # Nhân viên là role USER như ở M2: manager, admin được admin xếp vào bộ phận thì không phải.
    employee = await create_user(db_session, department=department)
    await create_user(db_session, role=role, department=department)

    response = await client.get(EMPLOYEES_URL, headers=headers)

    assert listed_ids(response.json()) == [employee.id]


async def test_manager_does_not_list_employees_outside_scope(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    department: Department,
    headers: dict[str, str],
) -> None:
    other_manager = await create_user(db_session, role=UserRole.MANAGER)
    other = await create_department(db_session, managers=[other_manager])
    # Manager là thành viên bộ phận nhưng chưa được gán quản lý: ngoài phạm vi.
    own = await create_department(db_session, managers=[other_manager])
    manager.department_id = own.id
    await db_session.flush()
    deleted = await create_department(db_session, managers=[manager], deleted=True)
    employee = await create_user(db_session, department=department)
    for outside in (other, own, deleted):
        await create_user(db_session, department=outside)
    await create_user(db_session)

    response = await client.get(EMPLOYEES_URL, headers=headers)

    assert listed_ids(response.json()) == [employee.id]


async def test_manager_without_department_gets_empty_list(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_user(db_session, department=await create_department(db_session))

    response = await client.get(EMPLOYEES_URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"page": 1, "page_size": 20, "total": 0}}


async def test_manager_lists_employees_sorted_by_vietnamese_name(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    # Sắp theo byte thì chữ thường, chữ có dấu đứng sau "Z": "Bình, Zung, an, Ánh, Đặng".
    for full_name in ["Zung", "Đặng", "an", "Bình", "Ánh"]:
        await create_user(db_session, full_name=full_name, department=department)

    response = await client.get(EMPLOYEES_URL, headers=headers)

    assert [e["full_name"] for e in response.json()["data"]] == [
        "an",
        "Ánh",
        "Bình",
        "Đặng",
        "Zung",
    ]


async def test_manager_lists_employees_paginated(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    await create_user(db_session, full_name="An", department=department)
    second = await create_user(db_session, full_name="Bình", department=department)

    response = await client.get(EMPLOYEES_URL, params={"page": 2, "page_size": 1}, headers=headers)

    assert response.json()["meta"] == {"page": 2, "page_size": 1, "total": 2}
    assert listed_ids(response.json()) == [second.id]


@pytest.mark.parametrize(
    "keyword",
    ["nguyen van an", "NGUYỄN VĂN", "  văn an  ", "an.nguyen@", "EXAMPLE.ORG", "%"],
    ids=["no-accent", "upper-accent", "trimmed", "email-part", "email-upper", "like-wildcard"],
)
async def test_manager_searches_employees_by_name_and_email_within_scope(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    keyword: str,
) -> None:
    target = await create_user(
        db_session,
        email="an.nguyen@example.org",
        full_name="Nguyễn Văn An %",
        department=department,
    )
    await create_user(
        db_session, email="binh@example.com", full_name="Trần Thị Bình", department=department
    )
    # Khớp từ khóa nhưng ở bộ phận khác: tìm kiếm không được mở rộng phạm vi.
    await create_user(
        db_session,
        email="an.nguyen@example.org.vn",
        full_name="Nguyễn Văn An %",
        department=await create_department(db_session),
    )

    response = await client.get(EMPLOYEES_URL, params={"keyword": keyword}, headers=headers)

    assert listed_ids(response.json()) == [target.id]


async def test_manager_filters_employees_by_managed_department(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    department: Department,
    headers: dict[str, str],
) -> None:
    second = await create_department(db_session, managers=[manager])
    target = await create_user(db_session, department=second)
    await create_user(db_session, department=department)

    response = await client.get(EMPLOYEES_URL, params={"department_id": second.id}, headers=headers)

    assert response.status_code == 200
    assert listed_ids(response.json()) == [target.id]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"department_id": ID_MIN - 1}, "query.department_id"),
        ({"department_id": BIGINT_MAX + 1}, "query.department_id"),
        ({"keyword": "an\x00"}, "query.keyword"),
        ({"keyword": "a" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"page": 0}, "query.page"),
        ({"page_size": MAX_PAGE_SIZE + 1}, "query.page_size"),
    ],
    ids=[
        "department-id-too-small",
        "department-id-too-large",
        "keyword-nul",
        "keyword-too-long",
        "page",
        "page-size",
    ],
)
async def test_list_employees_rejects_invalid_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(EMPLOYEES_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


async def test_list_employees_validates_query_before_department_scope(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    # Thứ tự lỗi: tham số URL sai (422) trước phạm vi (404), kể cả với bộ phận ngoài phạm vi.
    outside = await create_department(db_session)

    response = await client.get(
        EMPLOYEES_URL, params={"department_id": outside.id, "page": 0}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "query.page"


# Chi tiết


async def test_manager_views_employee(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    employee = await create_user(
        db_session, email="an@example.com", full_name="Nguyễn Văn An", department=department
    )

    response = await client.get(employee_url(employee.id), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EMPLOYEE_FIELDS
    assert body["id"] == employee.id
    assert body["email"] == "an@example.com"
    assert body["role"] == "USER"
    assert body["department_id"] == department.id


async def test_manager_views_locked_employee(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    employee = await create_user(db_session, is_active=False, department=department)

    response = await client.get(employee_url(employee.id), headers=headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def _member_of_other_department(session: AsyncSession, manager: User) -> int:
    return (await create_user(session, department=await create_department(session))).id


async def _member_of_department_manager_belongs_to(session: AsyncSession, manager: User) -> int:
    # Manager là thành viên nhưng chưa được gán quản lý bộ phận này.
    own = await create_department(session)
    manager.department_id = own.id
    await session.flush()
    return (await create_user(session, department=own)).id


async def _member_of_deleted_department(session: AsyncSession, manager: User) -> int:
    deleted = await create_department(session, managers=[manager], deleted=True)
    return (await create_user(session, department=deleted)).id


async def _deleted_member(session: AsyncSession, manager: User) -> int:
    department = await create_department(session, managers=[manager])
    return (await create_user(session, deleted=True, department=department)).id


async def _manager_member(session: AsyncSession, manager: User) -> int:
    department = await create_department(session, managers=[manager])
    return (await create_user(session, role=UserRole.MANAGER, department=department)).id


async def _user_without_department(session: AsyncSession, manager: User) -> int:
    await create_department(session, managers=[manager])
    return (await create_user(session)).id


async def _missing_user(session: AsyncSession, manager: User) -> int:
    await create_department(session, managers=[manager])
    return BIGINT_MAX


@pytest.mark.parametrize(
    "arrange",
    [
        _member_of_other_department,
        _member_of_department_manager_belongs_to,
        _member_of_deleted_department,
        _deleted_member,
        _manager_member,
        _user_without_department,
        _missing_user,
    ],
    ids=[
        "other-department",
        "department-not-assigned",
        "deleted-department",
        "deleted-user",
        "manager-member",
        "no-department",
        "missing",
    ],
)
async def test_employee_outside_scope_is_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    arrange: Callable[[AsyncSession, User], Awaitable[int]],
) -> None:
    user_id = await arrange(db_session, manager)

    response = await client.get(employee_url(user_id), headers=headers)

    assert response.status_code == 404
    assert response.json() == error_json(UserNotFoundError())


@pytest.mark.parametrize("user_id", [ID_MIN - 1, BIGINT_MAX + 1, "abc"])
async def test_get_employee_rejects_invalid_id(
    client: AsyncClient, headers: dict[str, str], user_id: int | str
) -> None:
    response = await client.get(employee_url(user_id), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "path.user_id"


# Phân quyền, Swagger


@pytest.mark.parametrize("url", [EMPLOYEES_URL, employee_url(ID_MIN)], ids=["list", "detail"])
@pytest.mark.parametrize(
    ("role", "error"),
    [
        (None, UnauthorizedError()),
        (UserRole.USER, ForbiddenError()),
        (UserRole.ADMIN, ForbiddenError()),
    ],
    ids=["anonymous", "user", "admin"],
)
async def test_employee_endpoints_require_manager_role(
    client: AsyncClient,
    db_session: AsyncSession,
    url: str,
    role: UserRole | None,
    error: AppError,
) -> None:
    headers = auth_headers(await create_user(db_session, role=role)) if role else {}

    response = await client.get(url, headers=headers)

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


@pytest.mark.parametrize("path", ["/manager/employees", "/manager/employees/{user_id}"])
async def test_employee_endpoints_document_errors_in_swagger(
    client: AsyncClient, path: str
) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    responses = paths[f"{API}{path}"]["get"]["responses"]
    for status_code in ("401", "403", "404", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
