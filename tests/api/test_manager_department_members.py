"""Manager xem ứng viên, thêm, gỡ nhân viên trong bộ phận mình quản lý (M2).

Phạm vi bộ phận (401, 403, 404 theo ma trận quyền) chạy tự động cho hai endpoint
`/manager/departments/{department_id}/members...` ở test_department_scope.py.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, DEPARTMENT_MEMBERS_ADD_MAX, ID_MIN
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.exceptions import (
    DepartmentNotFoundError,
    EmployeeRoleRequiredError,
    InvalidMemberCandidateError,
)
from app.modules.departments.models import Department
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user
from tests.helpers import error_json

API = get_settings().api_v1_prefix
CANDIDATES_URL = f"{API}/manager/candidates"
MISSING_ID = BIGINT_MAX


def members_url(department_id: int) -> str:
    return f"{API}/manager/departments/{department_id}/members"


def member_url(department_id: int, user_id: int) -> str:
    return f"{members_url(department_id)}/{user_id}"


async def department_of(session: AsyncSession, user: User) -> int | None:
    await session.refresh(user)
    return user.department_id


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, role=UserRole.MANAGER)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, managers=[manager])


@pytest.fixture
def headers(manager: User) -> dict[str, str]:
    return auth_headers(manager)


# Ứng viên


async def test_manager_lists_candidates_sorted_by_name(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    names = ["Zung", "Đặng Văn Hải", "an", "Ánh", "Bình"]
    candidates = {name: await create_user(db_session, full_name=name) for name in names}
    # Nhân viên mới chưa đặt mật khẩu vẫn được xếp bộ phận trước lần đăng nhập đầu.
    candidates["Cường"] = await create_user(db_session, full_name="Cường", password=None)
    other = await create_department(db_session)
    # Không phải ứng viên: đã có bộ phận, bị khóa, đã xóa, role khác USER.
    non_candidates: list[dict[str, Any]] = [
        {"department": department},
        {"department": other},
        {"is_active": False},
        {"deleted": True},
        {"role": UserRole.MANAGER},
        {"role": UserRole.ADMIN},
    ]
    for overrides in non_candidates:
        await create_user(db_session, full_name="Ánh", **overrides)

    response = await client.get(CANDIDATES_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    expected = ["an", "Ánh", "Bình", "Cường", "Đặng Văn Hải", "Zung"]
    assert body["data"] == [
        {"id": candidates[name].id, "email": candidates[name].email, "full_name": name}
        for name in expected
    ]
    assert body["meta"] == {"page": 1, "page_size": 20, "total": len(expected)}


@pytest.mark.parametrize("keyword", ["dang van", "ĐẶNG", "hai.dang@"], ids=str)
async def test_candidates_are_searched_by_name_without_accents_or_email(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], keyword: str
) -> None:
    match = await create_user(db_session, full_name="Đặng Văn Hải", email="hai.dang@example.com")
    await create_user(db_session, full_name="Nguyễn Văn An")

    response = await client.get(CANDIDATES_URL, params={"keyword": keyword}, headers=headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [match.id]


async def test_candidates_are_paginated(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    users = [await create_user(db_session, full_name=name) for name in ["An", "Bình", "Cường"]]

    response = await client.get(CANDIDATES_URL, params={"page": 2, "page_size": 2}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["data"]] == [users[2].id]
    assert body["meta"] == {"page": 2, "page_size": 2, "total": 3}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page_size": 0}, "query.page_size"),
        ({"keyword": "a\x00b"}, "query.keyword"),
    ],
    ids=["page-size-zero", "keyword-nul"],
)
async def test_candidates_validate_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(CANDIDATES_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


@pytest.mark.parametrize(
    ("role", "error"),
    [
        (None, UnauthorizedError()),
        (UserRole.USER, ForbiddenError()),
        (UserRole.ADMIN, ForbiddenError()),
    ],
    ids=["anonymous", "user", "admin"],
)
async def test_only_manager_lists_candidates(
    client: AsyncClient, db_session: AsyncSession, role: UserRole | None, error: AppError
) -> None:
    headers = auth_headers(await create_user(db_session, role=role)) if role else {}

    response = await client.get(CANDIDATES_URL, headers=headers)

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


# Thêm nhân viên


async def test_manager_adds_candidates_to_department(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    first = await create_user(db_session)
    pending = await create_user(db_session, password=None)

    response = await client.post(
        members_url(department.id), json={"user_ids": [first.id, pending.id]}, headers=headers
    )

    assert response.status_code == 204
    assert response.content == b""
    assert await department_of(db_session, first) == department.id
    assert await department_of(db_session, pending) == department.id


async def test_adding_members_again_does_not_fail(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    # Client timeout rồi gửi lại, hoặc gửi kèm người đã là thành viên (kể cả role khác, bị khóa).
    candidate = await create_user(db_session)
    locked_member = await create_user(db_session, is_active=False, department=department)
    manager_member = await create_user(db_session, role=UserRole.MANAGER, department=department)
    body = {"user_ids": [candidate.id, candidate.id, locked_member.id, manager_member.id]}

    first = await client.post(members_url(department.id), json=body, headers=headers)
    second = await client.post(members_url(department.id), json=body, headers=headers)

    assert (first.status_code, second.status_code) == (204, 204)
    for user in (candidate, locked_member, manager_member):
        assert await department_of(db_session, user) == department.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"deleted": True},
        {"is_active": False},
        {"role": UserRole.MANAGER},
        {"role": UserRole.ADMIN},
        {"in_other_department": True},
        {"missing": True},
    ],
    ids=["deleted", "locked", "manager", "admin", "other-department", "missing"],
)
async def test_add_members_rejects_non_candidates_and_adds_nobody(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    overrides: dict[str, Any],
) -> None:
    candidate = await create_user(db_session)
    if overrides.pop("missing", False):
        invalid_id = MISSING_ID
    else:
        if overrides.pop("in_other_department", False):
            overrides["department"] = await create_department(db_session)
        invalid = await create_user(db_session, **overrides)
        invalid_id = invalid.id
    # Commit dữ liệu chuẩn bị: service rollback để nhả khóa dòng, chỉ bỏ phần service đã ghi.
    await db_session.commit()

    response = await client.post(
        members_url(department.id), json={"user_ids": [candidate.id, invalid_id]}, headers=headers
    )

    assert response.status_code == 422
    assert response.json() == error_json(InvalidMemberCandidateError([invalid_id]))
    assert await department_of(db_session, candidate) is None


async def test_add_members_lists_every_invalid_id_in_request_order(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    locked = await create_user(db_session, is_active=False)
    candidate = await create_user(db_session)

    response = await client.post(
        members_url(department.id),
        json={"user_ids": [MISSING_ID, candidate.id, locked.id]},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {
        "field": "user_ids",
        "invalid_ids": [MISSING_ID, locked.id],
    }


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "body.user_ids"),
        ({"user_ids": None}, "body.user_ids"),
        ({"user_ids": []}, "body.user_ids"),
        ({"user_ids": [ID_MIN - 1]}, "body.user_ids.0"),
        ({"user_ids": [BIGINT_MAX + 1]}, "body.user_ids.0"),
        ({"user_ids": ["abc"]}, "body.user_ids.0"),
        ({"user_ids": list(range(1, DEPARTMENT_MEMBERS_ADD_MAX + 2))}, "body.user_ids"),
        ({"user_ids": [1], "role": "USER"}, "body.role"),
    ],
    ids=[
        "missing",
        "null",
        "empty",
        "id-zero",
        "id-over-bigint",
        "id-not-number",
        "too-many",
        "unknown-field",
    ],
)
async def test_add_members_validates_body(
    client: AsyncClient,
    department: Department,
    headers: dict[str, str],
    body: dict[str, Any],
    field: str,
) -> None:
    response = await client.post(members_url(department.id), json=body, headers=headers)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == field


async def test_add_members_accepts_full_batch(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    users = [await create_user(db_session) for _ in range(DEPARTMENT_MEMBERS_ADD_MAX)]

    response = await client.post(
        members_url(department.id), json={"user_ids": [u.id for u in users]}, headers=headers
    )

    assert response.status_code == 204
    assert await department_of(db_session, users[-1]) == department.id


async def test_manager_cannot_add_members_to_department_outside_scope(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    other = await create_department(db_session)
    candidate = await create_user(db_session)

    response = await client.post(
        members_url(other.id), json={"user_ids": [candidate.id]}, headers=headers
    )

    assert response.status_code == 404
    assert response.json() == error_json(DepartmentNotFoundError())
    assert await department_of(db_session, candidate) is None


# Gỡ nhân viên


async def test_manager_removes_member_from_department(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    member = await create_user(db_session, department=department)

    response = await client.delete(member_url(department.id, member.id), headers=headers)

    assert response.status_code == 204
    assert await department_of(db_session, member) is None
    # Chỉ gỡ liên kết: tài khoản vẫn đăng nhập được, quay lại danh sách ứng viên.
    assert member.can_log_in
    candidates = (await client.get(CANDIDATES_URL, headers=headers)).json()["data"]
    assert [item["id"] for item in candidates] == [member.id]


async def test_removing_member_again_does_not_fail(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    member = await create_user(db_session, department=department)

    first = await client.delete(member_url(department.id, member.id), headers=headers)
    second = await client.delete(member_url(department.id, member.id), headers=headers)

    assert (first.status_code, second.status_code) == (204, 204)


async def test_manager_removes_locked_member(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    member = await create_user(db_session, is_active=False, department=department)

    response = await client.delete(member_url(department.id, member.id), headers=headers)

    assert response.status_code == 204
    assert await department_of(db_session, member) is None


@pytest.mark.parametrize("in_other_department", [False, True], ids=["no-department", "other"])
async def test_removing_non_member_changes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    in_other_department: bool,
) -> None:
    other = await create_department(db_session) if in_other_department else None
    user = await create_user(db_session, department=other)
    other_id = other.id if other else None
    # Commit dữ liệu chuẩn bị: service rollback để nhả khóa dòng, chỉ bỏ phần service đã ghi.
    # Rollback làm mọi object trong session hết hạn: giữ id trước khi gọi.
    await db_session.commit()

    response = await client.delete(member_url(department.id, user.id), headers=headers)

    assert response.status_code == 204
    assert await department_of(db_session, user) == other_id


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "deleted"])
async def test_remove_member_rejects_unknown_user(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    deleted: bool,
) -> None:
    # Id gõ nhầm không được trả 204 như đã gỡ xong.
    user_id = (
        (await create_user(db_session, deleted=True, department=department)).id
        if deleted
        else MISSING_ID
    )

    response = await client.delete(member_url(department.id, user_id), headers=headers)

    assert response.status_code == 404
    assert response.json() == error_json(UserNotFoundError())


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
async def test_manager_cannot_remove_member_with_other_role(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    headers: dict[str, str],
    role: UserRole,
) -> None:
    member = await create_user(db_session, role=role, department=department)
    department_id = department.id
    # Commit dữ liệu chuẩn bị: service rollback để nhả khóa dòng, chỉ bỏ phần service đã ghi.
    # Rollback làm mọi object trong session hết hạn: giữ id trước khi gọi.
    await db_session.commit()

    response = await client.delete(member_url(department_id, member.id), headers=headers)

    assert response.status_code == 422
    assert response.json() == error_json(EmployeeRoleRequiredError())
    assert await department_of(db_session, member) == department_id


@pytest.mark.parametrize("user_id", [ID_MIN - 1, BIGINT_MAX + 1, "abc"])
async def test_remove_member_rejects_invalid_user_id(
    client: AsyncClient, department: Department, headers: dict[str, str], user_id: int | str
) -> None:
    response = await client.delete(f"{members_url(department.id)}/{user_id}", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "path.user_id"
