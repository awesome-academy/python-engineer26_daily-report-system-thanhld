"""Admin gán, gỡ manager cho bộ phận, xem thành viên để chọn manager (A3)."""

from collections.abc import Callable
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, ID_MIN
from app.modules.departments.models import DepartmentManager
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user

API = get_settings().api_v1_prefix
UrlBuilder = Callable[[int], str]
MISSING_ID = BIGINT_MAX


def members_url(department_id: int) -> str:
    return f"{API}/admin/departments/{department_id}/members"


def managers_url(department_id: int) -> str:
    return f"{API}/admin/departments/{department_id}/managers"


def manager_url(department_id: int, user_id: int) -> str:
    return f"{managers_url(department_id)}/{user_id}"


async def manager_ids(session: AsyncSession, department_id: int) -> set[int]:
    rows = await session.scalars(
        select(DepartmentManager.user_id).where(DepartmentManager.department_id == department_id)
    )
    return set(rows)


@pytest.fixture
async def admin(db_session: AsyncSession) -> User:
    return await create_user(db_session, role=UserRole.ADMIN)


# Xem thành viên


async def test_admin_lists_department_members_with_manager_flag(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)
    other = await create_department(db_session)
    manager = await create_user(
        db_session, full_name="Bùi Thị Bình", role=UserRole.MANAGER, department=department
    )
    locked = await create_user(
        db_session, full_name="Trần Văn Cường", is_active=False, department=department
    )
    member = await create_user(db_session, full_name="Lê Văn An", department=department)
    await create_user(db_session, full_name="Đã Xóa", deleted=True, department=department)
    await create_user(db_session, full_name="Bộ Phận Khác", department=other)
    db_session.add(DepartmentManager(department_id=department.id, user_id=manager.id))
    await db_session.flush()

    response = await client.get(members_url(department.id), headers=auth_headers(admin))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 3}
    assert [(m["id"], m["role"], m["is_active"], m["is_manager"]) for m in body["data"]] == [
        (manager.id, "MANAGER", True, True),
        (member.id, "USER", True, False),
        (locked.id, "USER", False, False),
    ]
    assert "password_hash" not in body["data"][0]


async def test_admin_lists_department_members_sorted_by_vietnamese_name(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    # Sắp theo byte thì chữ thường, chữ có dấu đứng sau "Z": "Bình, Zung, an, Ánh, Đặng".
    department = await create_department(db_session)
    for full_name in ["Zung", "Đặng", "an", "Bình", "Ánh"]:
        await create_user(db_session, full_name=full_name, department=department)

    response = await client.get(members_url(department.id), headers=auth_headers(admin))

    assert response.status_code == 200
    assert [m["full_name"] for m in response.json()["data"]] == [
        "an",
        "Ánh",
        "Bình",
        "Đặng",
        "Zung",
    ]


async def test_admin_lists_department_members_paginated(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)
    await create_user(db_session, full_name="An", department=department)
    second = await create_user(db_session, full_name="Bình", department=department)

    response = await client.get(
        members_url(department.id), params={"page": 2, "page_size": 1}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["meta"] == {"page": 2, "page_size": 1, "total": 2}
    assert [m["id"] for m in response.json()["data"]] == [second.id]


async def test_admin_lists_members_of_empty_department(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)

    response = await client.get(members_url(department.id), headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json() == {"data": [], "meta": {"page": 1, "page_size": 20, "total": 0}}


# Gán manager


async def test_admin_assigns_manager_to_department(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)
    manager = await create_user(
        db_session, email="binh@example.com", full_name="Bùi Thị Bình", role=UserRole.MANAGER
    )

    response = await client.post(
        managers_url(department.id), json={"user_id": manager.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["email"], body["full_name"]) == (
        manager.id,
        "binh@example.com",
        "Bùi Thị Bình",
    )
    assert body["assigned_at"] is not None
    assert await manager_ids(db_session, department.id) == {manager.id}


async def test_department_has_many_managers_and_manager_has_many_departments(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    # Q2. Manager không cần là thành viên bộ phận (Q1: thành viên chỉ thuộc một bộ phận).
    first, second = await create_department(db_session), await create_department(db_session)
    binh = await create_user(db_session, role=UserRole.MANAGER, department=first)
    cuong = await create_user(db_session, role=UserRole.MANAGER)

    for department, manager in [(first, binh), (first, cuong), (second, binh)]:
        response = await client.post(
            managers_url(department.id), json={"user_id": manager.id}, headers=auth_headers(admin)
        )
        assert response.status_code == 200

    assert await manager_ids(db_session, first.id) == {binh.id, cuong.id}
    assert await manager_ids(db_session, second.id) == {binh.id}


async def test_assigning_existing_manager_again_keeps_assignment(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    assigned_at = await db_session.scalar(
        select(DepartmentManager.assigned_at).where(DepartmentManager.user_id == manager.id)
    )
    assert assigned_at is not None

    response = await client.post(
        managers_url(department.id), json={"user_id": manager.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["assigned_at"]) == assigned_at
    assert await manager_ids(db_session, department.id) == {manager.id}


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.ADMIN])
async def test_assigning_non_manager_role_is_rejected(
    client: AsyncClient, db_session: AsyncSession, admin: User, role: UserRole
) -> None:
    department = await create_department(db_session)
    user = await create_user(db_session, role=role)
    await db_session.commit()
    # Service rollback khi lỗi làm mọi object trong session hết hạn: giữ id trước khi gọi.
    department_id = department.id

    response = await client.post(
        managers_url(department_id), json={"user_id": user.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "MANAGER_ROLE_REQUIRED",
        "message": "Chỉ gán được tài khoản có role MANAGER làm manager bộ phận.",
        "details": {"field": "user_id"},
    }
    assert await manager_ids(db_session, department_id) == set()


async def test_assigning_locked_manager_is_rejected(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)
    manager = await create_user(db_session, role=UserRole.MANAGER, is_active=False)
    await db_session.commit()
    # Service rollback khi lỗi làm mọi object trong session hết hạn: giữ id trước khi gọi.
    department_id = department.id

    response = await client.post(
        managers_url(department_id), json={"user_id": manager.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "USER_INACTIVE"
    assert response.json()["error"]["details"] == {"field": "user_id"}
    assert await manager_ids(db_session, department_id) == set()


async def test_assigning_manager_without_password_yet_is_allowed(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    # Tài khoản admin vừa tạo, chưa đặt mật khẩu (S2) vẫn đang hoạt động.
    department = await create_department(db_session)
    manager = await create_user(db_session, role=UserRole.MANAGER, password=None)

    response = await client.post(
        managers_url(department.id), json={"user_id": manager.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 200


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "soft-deleted"])
async def test_assigning_unknown_user_returns_not_found(
    client: AsyncClient, db_session: AsyncSession, admin: User, deleted: bool
) -> None:
    department = await create_department(db_session)
    user_id = (
        (await create_user(db_session, role=UserRole.MANAGER, deleted=True)).id
        if deleted
        else MISSING_ID
    )

    response = await client.post(
        managers_url(department.id), json={"user_id": user_id}, headers=auth_headers(admin)
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Người dùng không tồn tại hoặc đã bị xóa.",
        "details": {"field": "user_id"},
    }


@pytest.mark.parametrize(
    "body",
    [{}, {"user_id": ID_MIN - 1}, {"user_id": "abc"}, {"user_id": BIGINT_MAX + 1}],
    ids=["missing", "zero", "not-int", "over-bigint"],
)
async def test_assigning_manager_validates_body(
    client: AsyncClient, db_session: AsyncSession, admin: User, body: dict[str, object]
) -> None:
    department = await create_department(db_session)

    response = await client.post(
        managers_url(department.id), json=body, headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert [d["field"] for d in response.json()["error"]["details"]] == ["body.user_id"]


# Gỡ manager


async def test_admin_removes_manager_from_department(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    other = await create_department(db_session, managers=[manager])

    response = await client.delete(
        manager_url(department.id, manager.id), headers=auth_headers(admin)
    )

    assert response.status_code == 204
    assert await manager_ids(db_session, department.id) == set()
    # Chỉ gỡ liên kết với bộ phận này: tài khoản và bộ phận khác giữ nguyên.
    assert await manager_ids(db_session, other.id) == {manager.id}
    await db_session.refresh(manager)
    assert manager.deleted_at is None


async def test_removing_non_manager_is_no_op(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    member = await create_user(db_session, department=department)

    response = await client.delete(
        manager_url(department.id, member.id), headers=auth_headers(admin)
    )

    assert response.status_code == 204
    assert await manager_ids(db_session, department.id) == {manager.id}


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "soft-deleted"])
async def test_removing_unknown_user_returns_not_found(
    client: AsyncClient, db_session: AsyncSession, admin: User, deleted: bool
) -> None:
    # Id gõ nhầm không được trả 204 như đã gỡ xong.
    department = await create_department(db_session)
    user_id = (
        (await create_user(db_session, role=UserRole.MANAGER, deleted=True)).id
        if deleted
        else MISSING_ID
    )

    response = await client.delete(manager_url(department.id, user_id), headers=auth_headers(admin))

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Người dùng không tồn tại hoặc đã bị xóa.",
        "details": {"field": "user_id"},
    }


async def test_removing_manager_validates_user_id(
    client: AsyncClient, db_session: AsyncSession, admin: User
) -> None:
    department = await create_department(db_session)

    response = await client.delete(
        manager_url(department.id, ID_MIN - 1), headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["path.user_id"]


# Chung cho cả ba endpoint

Endpoint = tuple[str, UrlBuilder]
ENDPOINTS: list[Endpoint] = [
    ("GET", members_url),
    ("POST", managers_url),
    ("DELETE", lambda department_id: manager_url(department_id, 1)),
]
ENDPOINT_IDS = ["members", "assign", "remove"]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ENDPOINT_IDS)
@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "soft-deleted"])
async def test_unknown_department_returns_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    admin: User,
    endpoint: Endpoint,
    deleted: bool,
) -> None:
    method, url = endpoint
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department_id = (
        (await create_department(db_session, deleted=True)).id if deleted else MISSING_ID
    )

    response = await client.request(
        method, url(department_id), json={"user_id": manager.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Không tìm thấy bộ phận.",
        "details": {"field": "department_id"},
    }


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ENDPOINT_IDS)
async def test_department_id_over_bigint_is_validation_error(
    client: AsyncClient, admin: User, endpoint: Endpoint
) -> None:
    method, url = endpoint

    response = await client.request(
        method, url(BIGINT_MAX + 1), json={"user_id": 1}, headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["path.department_id"]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ENDPOINT_IDS)
async def test_endpoints_require_token(client: AsyncClient, endpoint: Endpoint) -> None:
    method, url = endpoint

    response = await client.request(method, url(1), json={"user_id": 1})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ENDPOINT_IDS)
@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MANAGER])
async def test_endpoints_reject_non_admin(
    client: AsyncClient, db_session: AsyncSession, endpoint: Endpoint, role: UserRole
) -> None:
    method, url = endpoint
    user = await create_user(db_session, role=role)
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session)

    response = await client.request(
        method, url(department.id), json={"user_id": manager.id}, headers=auth_headers(user)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert await manager_ids(db_session, department.id) == set()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/departments/{department_id}/members"),
        ("post", "/admin/departments/{department_id}/managers"),
        ("delete", "/admin/departments/{department_id}/managers/{user_id}"),
    ],
    ids=ENDPOINT_IDS,
)
async def test_endpoints_document_errors_in_swagger(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.get("/openapi.json")

    responses = response.json()["paths"][f"{API}{path}"][method]["responses"]
    for status_code in ("401", "403", "404", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
