from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import (
    BIGINT_MAX,
    DEPARTMENT_CODE_MAX_LENGTH,
    DEPARTMENT_DESCRIPTION_MAX_LENGTH,
    DEPARTMENT_NAME_MAX_LENGTH,
    KEYWORD_MAX_LENGTH,
)
from app.modules.departments.models import Department, DepartmentManager
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user

DEPARTMENTS_URL = f"{get_settings().api_v1_prefix}/admin/departments"


def department_url(department_id: int) -> str:
    return f"{DEPARTMENTS_URL}/{department_id}"


@pytest.fixture
async def admin(db_session: AsyncSession) -> User:
    return await create_user(db_session, role=UserRole.ADMIN)


@pytest.fixture
def headers(admin: User) -> dict[str, str]:
    return auth_headers(admin)


def error_code(body: dict[str, Any]) -> str:
    code: str = body["error"]["code"]
    return code


# Phân quyền: gọi endpoint thật để chứng minh router đã nằm trong nhóm /admin.


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ""),
        ("POST", ""),
        ("GET", "/1"),
        ("PATCH", "/1"),
        ("DELETE", "/1"),
    ],
)
async def test_departments_endpoints_require_login(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{DEPARTMENTS_URL}{path}")

    assert response.status_code == 401
    assert error_code(response.json()) == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.USER])
async def test_non_admin_cannot_manage_departments(
    client: AsyncClient, db_session: AsyncSession, role: UserRole
) -> None:
    user = await create_user(db_session, role=role)
    department = await create_department(db_session)

    responses = [
        await client.get(DEPARTMENTS_URL, headers=auth_headers(user)),
        await client.delete(department_url(department.id), headers=auth_headers(user)),
    ]

    assert [r.status_code for r in responses] == [403, 403]
    assert department.deleted_at is None


# Tạo


async def test_admin_creates_department_with_normalized_code(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post(
        DEPARTMENTS_URL,
        json={"code": " qa-team ", "name": " Phòng Kiểm thử ", "description": "Kiểm thử"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["code"], body["name"], body["description"]) == (
        "QA-TEAM",
        "Phòng Kiểm thử",
        "Kiểm thử",
    )
    assert body["id"] > 0
    assert body["created_at"]
    assert body["updated_at"]


@pytest.mark.parametrize("description", ["", "   "], ids=["empty", "spaces"])
async def test_create_department_stores_blank_description_as_null(
    client: AsyncClient, headers: dict[str, str], description: str
) -> None:
    response = await client.post(
        DEPARTMENTS_URL,
        json={"code": "DEV", "name": "Phòng", "description": description},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["description"] is None


async def test_create_department_rejects_code_differing_only_in_case(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_department(db_session, code="DEV")

    response = await client.post(
        DEPARTMENTS_URL, json={"code": "dev", "name": "Phòng khác"}, headers=headers
    )

    assert response.status_code == 409
    assert error_code(response.json()) == "DEPARTMENT_CODE_ALREADY_EXISTS"
    assert response.json()["error"]["details"] == {"field": "code"}


async def test_create_department_reuses_code_of_deleted_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_department(db_session, code="DEV", deleted=True)

    response = await client.post(
        DEPARTMENTS_URL, json={"code": "DEV", "name": "Phòng Phát triển"}, headers=headers
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": "Phòng Kỹ thuật"}, "body.code"),
        ({"code": "   ", "name": "Phòng Kỹ thuật"}, "body.code"),
        ({"code": "KỸ", "name": "Phòng Kỹ thuật"}, "body.code"),
        ({"code": "DEV TEAM", "name": "Phòng Kỹ thuật"}, "body.code"),
        ({"code": "D" * (DEPARTMENT_CODE_MAX_LENGTH + 1), "name": "Phòng"}, "body.code"),
        ({"code": "DEV"}, "body.name"),
        ({"code": "DEV", "name": "   "}, "body.name"),
        ({"code": "DEV", "name": "P" * (DEPARTMENT_NAME_MAX_LENGTH + 1)}, "body.name"),
        (
            {
                "code": "DEV",
                "name": "Phòng",
                "description": "x" * (DEPARTMENT_DESCRIPTION_MAX_LENGTH + 1),
            },
            "body.description",
        ),
        ({"code": "ß" * 11, "name": "Phòng"}, "body.code"),
        ({"code": "ß", "name": "Phòng"}, "body.code"),
        # Chữ i không chấm (U+0131), upper() thành "I".
        ({"code": "\u0131" * 3, "name": "Phòng"}, "body.code"),
        ({"code": "DEV", "name": "Phòng\x00"}, "body.name"),
        ({"code": "DEV", "name": "Phòng", "description": "Mô tả\x00"}, "body.description"),
    ],
    ids=[
        "missing-code",
        "blank-code",
        "code-with-diacritics",
        "code-with-space",
        "code-too-long",
        "missing-name",
        "blank-name",
        "name-too-long",
        "description-too-long",
        "code-longer-after-upper",
        "code-sharp-s",
        "code-dotless-i",
        "name-with-nul",
        "description-with-nul",
    ],
)
async def test_create_department_rejects_invalid_data(
    client: AsyncClient, headers: dict[str, str], payload: dict[str, Any], field: str
) -> None:
    response = await client.post(DEPARTMENTS_URL, json=payload, headers=headers)

    assert response.status_code == 422
    body = response.json()
    assert error_code(body) == "VALIDATION_ERROR"
    assert [d["field"] for d in body["error"]["details"]] == [field]


# Danh sách


async def test_list_departments_paginates_active_departments_sorted_by_code(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    for code in ("QA", "DEV", "HR"):
        await create_department(db_session, code=code)
    await create_department(db_session, code="OLD", deleted=True)

    response = await client.get(DEPARTMENTS_URL, params={"page_size": 2}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [d["code"] for d in body["data"]] == ["DEV", "HR"]
    assert body["meta"] == {"page": 1, "page_size": 2, "total": 3}


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("ky thuat", ["KT"]),
        ("KỸ THUẬT", ["KT"]),
        ("qa", ["QA"]),
        ("phòng", ["KT", "QA", "SALE"]),
        ("50%", ["SALE"]),
        ("   ", ["KT", "QA", "SALE"]),
    ],
    ids=[
        "name-without-diacritics",
        "name-uppercase",
        "code",
        "common-word",
        "like-wildcard",
        "blank",
    ],
)
async def test_list_departments_searches_by_code_or_name(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    keyword: str,
    expected: list[str],
) -> None:
    await create_department(db_session, code="KT", name="Phòng Kỹ thuật")
    await create_department(db_session, code="QA", name="Phòng Kiểm thử")
    await create_department(db_session, code="SALE", name="Phòng Kinh doanh 50%")

    response = await client.get(DEPARTMENTS_URL, params={"keyword": keyword}, headers=headers)

    assert response.status_code == 200
    assert [d["code"] for d in response.json()["data"]] == expected


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page": 0}, "query.page"),
        ({"page_size": 0}, "query.page_size"),
        ({"keyword": "k" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"keyword": "k\x00"}, "query.keyword"),
    ],
    ids=["page-zero", "page-size-zero", "keyword-too-long", "keyword-with-nul"],
)
async def test_list_departments_rejects_invalid_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(DEPARTMENTS_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


# Xem


async def test_admin_gets_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, code="DEV", name="Phòng Phát triển")

    response = await client.get(department_url(department.id), headers=headers)

    assert response.status_code == 200
    assert (response.json()["id"], response.json()["code"]) == (department.id, "DEV")


@pytest.mark.parametrize("deleted", [True, False], ids=["deleted", "missing"])
async def test_get_department_returns_404_for_deleted_or_missing(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], deleted: bool
) -> None:
    department_id = (await create_department(db_session, deleted=True)).id if deleted else 999999

    response = await client.get(department_url(department_id), headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"field": "department_id"}


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("department_id", [0, BIGINT_MAX + 1], ids=["zero", "over-bigint"])
async def test_department_id_out_of_range_returns_422(
    client: AsyncClient, headers: dict[str, str], method: str, department_id: int
) -> None:
    # Số vượt bigint không được chạm DB: asyncpg từ chối tham số và API trả 500.
    response = await client.request(
        method, department_url(department_id), json={"name": "Phòng"}, headers=headers
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["path.department_id"]


# Sửa


async def test_patch_department_updates_only_sent_fields(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(
        db_session, code="DEV", name="Phòng Phát triển", description="Mô tả cũ"
    )

    response = await client.patch(
        department_url(department.id),
        json={"name": "Phòng Phát triển sản phẩm", "description": None},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["code"], body["name"], body["description"]) == (
        "DEV",
        "Phòng Phát triển sản phẩm",
        None,
    )


async def test_patch_department_stores_blank_description_as_null(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, description="Mô tả cũ")

    response = await client.patch(
        department_url(department.id), json={"description": "  "}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["description"] is None


async def test_patch_department_changes_code(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, code="DEV")

    response = await client.patch(
        department_url(department.id), json={"code": "rnd"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["code"] == "RND"


async def test_patch_department_keeps_own_code_in_other_case(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, code="DEV")

    response = await client.patch(
        department_url(department.id), json={"code": "dev", "name": "Phòng mới"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["code"] == "DEV"


async def test_patch_department_rejects_code_of_other_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_department(db_session, code="QA")
    department = await create_department(db_session, code="DEV")

    response = await client.patch(
        department_url(department.id), json={"code": "qa"}, headers=headers
    )

    assert response.status_code == 409
    assert error_code(response.json()) == "DEPARTMENT_CODE_ALREADY_EXISTS"
    assert response.json()["error"]["details"] == {"field": "code"}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"code": None}, "body.code"),
        ({"name": None}, "body.name"),
        ({"code": "KỸ"}, "body.code"),
        ({"manager_id": 1}, "body.manager_id"),
        ({"name": "Phòng\x00"}, "body.name"),
    ],
    ids=["null-code", "null-name", "invalid-code", "unknown-field", "name-with-nul"],
)
async def test_patch_department_rejects_invalid_data(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    payload: dict[str, Any],
    field: str,
) -> None:
    department = await create_department(db_session)

    response = await client.patch(department_url(department.id), json=payload, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


async def test_patch_deleted_department_returns_404(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, deleted=True)

    response = await client.patch(
        department_url(department.id), json={"name": "Phòng mới"}, headers=headers
    )

    assert response.status_code == 404


# Xóa


async def test_delete_department_soft_deletes_and_removes_manager_links(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    department = await create_department(db_session, managers=[manager])
    # Thành viên đã bị xóa mềm không tính là còn thành viên.
    await create_user(db_session, department=department, deleted=True)

    response = await client.delete(department_url(department.id), headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    assert department.deleted_at is not None
    links = await db_session.scalars(
        select(DepartmentManager).where(DepartmentManager.department_id == department.id)
    )
    assert links.all() == []
    assert (await client.get(department_url(department.id), headers=headers)).status_code == 404


async def test_delete_department_with_members_returns_409(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session)
    await create_user(db_session, department=department)
    await create_user(db_session, department=department, is_active=False)

    response = await client.delete(department_url(department.id), headers=headers)

    assert response.status_code == 409
    body = response.json()
    assert error_code(body) == "DEPARTMENT_NOT_EMPTY"
    assert body["error"]["details"] == {"member_count": 2}
    still_active = await db_session.scalar(
        select(Department.deleted_at).where(Department.id == department.id)
    )
    assert still_active is None


@pytest.mark.parametrize("deleted", [True, False], ids=["deleted", "missing"])
async def test_delete_department_returns_404_for_deleted_or_missing(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], deleted: bool
) -> None:
    department_id = (await create_department(db_session, deleted=True)).id if deleted else 999999

    response = await client.delete(department_url(department_id), headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"field": "department_id"}
