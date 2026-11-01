"""Manager xem bộ phận mình quản lý và thành viên (M1).

Phạm vi của các route có `{department_id}` (ngoài phạm vi, bộ phận đã xóa, role sai, id sai)
chạy theo ma trận quyền ở tests/api/test_department_scope.py; ở đây là dữ liệu trả về.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import KEYWORD_MAX_LENGTH, MAX_PAGE, MAX_PAGE_SIZE
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.models import Department
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user
from tests.helpers import error_json, recorded_queries

API = get_settings().api_v1_prefix
DEPARTMENTS_URL = f"{API}/manager/departments"


def department_url(department_id: int) -> str:
    return f"{DEPARTMENTS_URL}/{department_id}"


def members_url(department_id: int) -> str:
    return f"{department_url(department_id)}/members"


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, full_name="Quản Lý", role=UserRole.MANAGER)


@pytest.fixture
def headers(manager: User) -> dict[str, str]:
    return auth_headers(manager)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, managers=[manager])


# Danh sách bộ phận


async def test_manager_lists_only_departments_assigned_to_them(
    client: AsyncClient, db_session: AsyncSession, manager: User, headers: dict[str, str]
) -> None:
    second = await create_department(db_session, code="B02", managers=[manager])
    first = await create_department(
        db_session, code="A01", name="Phòng Kinh doanh", description="Bán hàng", managers=[manager]
    )
    member_only = await create_department(db_session, code="C03")
    manager.department_id = member_only.id
    await create_department(db_session, code="D04", managers=[manager], deleted=True)
    other_manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, code="E05", managers=[other_manager])
    await db_session.flush()

    response = await client.get(DEPARTMENTS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 2}
    assert [d["id"] for d in body["data"]] == [first.id, second.id]
    assert set(body["data"][0]) == {"id", "code", "name", "description", "created_at", "updated_at"}
    assert body["data"][0]["description"] == "Bán hàng"


async def test_manager_without_departments_gets_empty_list(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get(DEPARTMENTS_URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"page": 1, "page_size": 20, "total": 0}}


async def test_manager_lists_departments_paginated(
    client: AsyncClient, db_session: AsyncSession, manager: User, headers: dict[str, str]
) -> None:
    await create_department(db_session, code="A01", managers=[manager])
    second = await create_department(db_session, code="B02", managers=[manager])

    response = await client.get(
        DEPARTMENTS_URL, params={"page": 2, "page_size": 1}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["meta"] == {"page": 2, "page_size": 1, "total": 2}
    assert [d["id"] for d in response.json()["data"]] == [second.id]


@pytest.mark.parametrize("keyword", ["ky thuat", "KỸ THUẬT", "kt0"])
async def test_manager_searches_departments_by_code_or_name_without_accents(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    keyword: str,
) -> None:
    target = await create_department(
        db_session, code="KT01", name="Phòng Kỹ thuật", managers=[manager]
    )
    await create_department(db_session, code="KD01", name="Phòng Kinh doanh", managers=[manager])
    # Khớp từ khóa nhưng ngoài phạm vi: tìm kiếm không được nới phạm vi.
    await create_department(db_session, code="KT02", name="Kỹ thuật 2")

    response = await client.get(DEPARTMENTS_URL, params={"keyword": keyword}, headers=headers)

    assert response.status_code == 200
    assert [d["id"] for d in response.json()["data"]] == [target.id]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page": 0}, "query.page"),
        ({"page": MAX_PAGE + 1}, "query.page"),
        ({"page_size": 0}, "query.page_size"),
        ({"keyword": "k" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"keyword": "k\x00"}, "query.keyword"),
    ],
    ids=["page-zero", "page-too-large", "page-size-zero", "keyword-too-long", "keyword-with-nul"],
)
async def test_list_departments_validates_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(DEPARTMENTS_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


@pytest.mark.parametrize(
    ("role", "error"),
    [
        (None, UnauthorizedError()),
        (UserRole.USER, ForbiddenError()),
        (UserRole.ADMIN, ForbiddenError()),
    ],
    ids=["anonymous", "user", "admin"],
)
async def test_list_departments_requires_manager_role(
    client: AsyncClient, db_session: AsyncSession, role: UserRole | None, error: AppError
) -> None:
    caller = await create_user(db_session, role=role) if role else None
    # Có liên kết manager (dữ liệu cũ) cũng không được xem khi role không phải MANAGER.
    await create_department(db_session, managers=[caller] if caller else [])

    response = await client.get(DEPARTMENTS_URL, headers=auth_headers(caller) if caller else {})

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


# Chi tiết bộ phận


async def test_manager_views_department_with_managers_and_member_count(
    client: AsyncClient, db_session: AsyncSession, manager: User, headers: dict[str, str]
) -> None:
    co_manager = await create_user(
        db_session, full_name="Ánh Đồng Quản", email="anh@example.com", role=UserRole.MANAGER
    )
    deleted_manager = await create_user(db_session, role=UserRole.MANAGER, deleted=True)
    department = await create_department(
        db_session,
        code="KT01",
        name="Phòng Kỹ thuật",
        description="Phát triển",
        managers=[manager, co_manager, deleted_manager],
    )
    await create_user(db_session, department=department)
    await create_user(db_session, is_active=False, department=department)
    await create_user(db_session, deleted=True, department=department)
    await create_user(db_session, department=await create_department(db_session))

    response = await client.get(department_url(department.id), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("id", "code", "name", "description")} == {
        "id": department.id,
        "code": "KT01",
        "name": "Phòng Kỹ thuật",
        "description": "Phát triển",
    }
    # Sắp theo họ tên không dấu: "Ánh" trước "Quản"; manager đã xóa không hiện.
    assert [(m["id"], m["email"], m["full_name"]) for m in body["managers"]] == [
        (co_manager.id, "anh@example.com", "Ánh Đồng Quản"),
        (manager.id, manager.email, "Quản Lý"),
    ]
    assert set(body["managers"][0]) == {"id", "email", "full_name", "assigned_at"}
    # Tài khoản bị khóa vẫn là thành viên; manager không thuộc bộ phận thì không tính.
    assert body["member_count"] == 2


async def test_department_detail_query_count_does_not_grow_with_people(
    client: AsyncClient, db_session: AsyncSession, manager: User, headers: dict[str, str]
) -> None:
    small = await create_department(db_session, managers=[manager])
    co_managers = [await create_user(db_session, role=UserRole.MANAGER) for _ in range(3)]
    large = await create_department(db_session, managers=[manager, *co_managers])
    for _ in range(5):
        await create_user(db_session, department=large)

    with recorded_queries(db_session) as small_queries:
        small_response = await client.get(department_url(small.id), headers=headers)
    with recorded_queries(db_session) as large_queries:
        large_response = await client.get(department_url(large.id), headers=headers)

    assert len(small_response.json()["managers"]) == 1
    assert len(large_response.json()["managers"]) == 4
    assert large_response.json()["member_count"] == 5
    assert len(large_queries) == len(small_queries)


# Thành viên


async def test_manager_lists_members_with_manager_flag(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    manager.department_id = department.id
    locked = await create_user(
        db_session, full_name="Trần Văn Cường", is_active=False, department=department
    )
    member = await create_user(db_session, full_name="Lê Văn An", department=department)
    await create_user(db_session, full_name="Đã Xóa", deleted=True, department=department)
    other = await create_department(db_session)
    await create_user(db_session, full_name="Bộ Phận Khác", department=other)
    await db_session.flush()

    response = await client.get(members_url(department.id), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 3}
    assert [(m["id"], m["role"], m["is_active"], m["is_manager"]) for m in body["data"]] == [
        (member.id, "USER", True, False),
        (manager.id, "MANAGER", True, True),
        (locked.id, "USER", False, False),
    ]
    assert set(body["data"][0]) == {"id", "email", "full_name", "role", "is_active", "is_manager"}


async def test_manager_lists_members_sorted_by_vietnamese_name(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    # Sắp theo byte thì chữ thường, chữ có dấu đứng sau "Z": "Bình, Zung, an, Ánh, Đặng".
    for full_name in ["Zung", "Đặng", "an", "Bình", "Ánh"]:
        await create_user(db_session, full_name=full_name, department=department)

    response = await client.get(members_url(department.id), headers=headers)

    names = [m["full_name"] for m in response.json()["data"]]
    assert names == ["an", "Ánh", "Bình", "Đặng", "Zung"]


async def test_manager_lists_members_paginated(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    await create_user(db_session, full_name="An", department=department)
    second = await create_user(db_session, full_name="Bình", department=department)

    response = await client.get(
        members_url(department.id), params={"page": 2, "page_size": 1}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["meta"] == {"page": 2, "page_size": 1, "total": 2}
    assert [m["id"] for m in response.json()["data"]] == [second.id]


@pytest.mark.parametrize(
    "keyword",
    ["nguyen van", "NGUYỄN", "  van an  ", "an.nguyen@", "AN.NGUYEN@EXAMPLE"],
    ids=["no-accents", "upper-accents", "trimmed", "email-part", "email-upper"],
)
async def test_manager_searches_members_by_name_without_accents_or_email(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    department: Department,
    keyword: str,
) -> None:
    target = await create_user(
        db_session,
        full_name="Nguyễn Văn An",
        email="an.nguyen@example.com",
        department=department,
    )
    await create_user(db_session, full_name="Trần Thị Bình", department=department)
    # Khớp từ khóa nhưng thuộc bộ phận khác: tìm kiếm chỉ trong bộ phận trên URL.
    await create_user(
        db_session,
        full_name="Nguyễn Văn An",
        email="an.nguyen2@example.com",
        department=await create_department(db_session),
    )

    response = await client.get(
        members_url(department.id), params={"keyword": keyword}, headers=headers
    )

    assert response.status_code == 200
    assert [m["id"] for m in response.json()["data"]] == [target.id]
    assert response.json()["meta"]["total"] == 1


@pytest.mark.parametrize("keyword", ["%", "_", "\\", "\uff05"])
async def test_member_search_treats_like_wildcards_as_text(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    department: Department,
    keyword: str,
) -> None:
    # % full-width thành % thường sau unaccent, vẫn phải được escape.
    target = await create_user(db_session, full_name="An % _ \\ Bình", department=department)
    await create_user(db_session, full_name="Cường", department=department)

    response = await client.get(
        members_url(department.id), params={"keyword": keyword}, headers=headers
    )

    assert [m["id"] for m in response.json()["data"]] == [target.id]


async def test_blank_member_keyword_does_not_filter(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    await create_user(db_session, department=department)
    await create_user(db_session, department=department)

    response = await client.get(
        members_url(department.id), params={"keyword": "   "}, headers=headers
    )

    assert response.json()["meta"]["total"] == 2


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page": 0}, "query.page"),
        ({"page_size": MAX_PAGE_SIZE + 1}, "query.page_size"),
        ({"keyword": "k" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"keyword": "k\x00"}, "query.keyword"),
    ],
    ids=["page-zero", "page-size-too-large", "keyword-too-long", "keyword-with-nul"],
)
async def test_list_members_validates_query(
    client: AsyncClient,
    headers: dict[str, str],
    department: Department,
    params: dict[str, Any],
    field: str,
) -> None:
    response = await client.get(members_url(department.id), params=params, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


async def test_member_list_query_count_does_not_grow_with_page_size(
    client: AsyncClient, db_session: AsyncSession, manager: User, headers: dict[str, str]
) -> None:
    small = await create_department(db_session, managers=[manager])
    await create_user(db_session, department=small)
    # Có cả thành viên là manager của bộ phận, để cờ is_manager phải tra cho nhiều người.
    co_managers = [await create_user(db_session, role=UserRole.MANAGER) for _ in range(3)]
    large = await create_department(db_session, managers=[manager, *co_managers])
    for co_manager in co_managers:
        co_manager.department_id = large.id
    for _ in range(5):
        await create_user(db_session, department=large)
    await db_session.flush()

    with recorded_queries(db_session) as small_queries:
        small_response = await client.get(members_url(small.id), headers=headers)
    with recorded_queries(db_session) as large_queries:
        large_response = await client.get(members_url(large.id), headers=headers)

    assert small_response.json()["meta"]["total"] == 1
    assert large_response.json()["meta"]["total"] == 8
    assert sum(m["is_manager"] for m in large_response.json()["data"]) == 3
    assert len(large_queries) == len(small_queries)


@pytest.mark.parametrize(
    ("path", "errors"),
    [
        ("/manager/departments", ("401", "403", "422")),
        ("/manager/departments/{department_id}", ("401", "403", "404", "422")),
        ("/manager/departments/{department_id}/members", ("401", "403", "404", "422")),
    ],
    ids=["list", "detail", "members"],
)
async def test_endpoints_document_errors_in_swagger(
    client: AsyncClient, path: str, errors: tuple[str, ...]
) -> None:
    response = await client.get("/openapi.json")

    responses = response.json()["paths"][f"{API}{path}"]["get"]["responses"]
    for status_code in errors:
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
