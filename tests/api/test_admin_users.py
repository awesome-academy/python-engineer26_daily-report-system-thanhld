from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, KEYWORD_MAX_LENGTH, MAX_PAGE_SIZE
from app.modules.users.models import User, UserRole
from tests.factories import (
    DEFAULT_PASSWORD,
    auth_headers,
    create_department,
    create_report,
    create_user,
)
from tests.helpers import bearer, login, login_tokens, refresh

API = get_settings().api_v1_prefix
USERS_URL = f"{API}/admin/users"
ME_URL = f"{API}/me"
NEW_USER = {"email": "binh@example.com", "full_name": "Trần Thị Bình"}


def user_url(user_id: int) -> str:
    return f"{USERS_URL}/{user_id}"


@pytest.fixture
async def admin(db_session: AsyncSession) -> User:
    return await create_user(
        db_session, email="admin@example.com", full_name="Quản trị viên", role=UserRole.ADMIN
    )


@pytest.fixture
def headers(admin: User) -> dict[str, str]:
    return auth_headers(admin)


async def get_user_row(session: AsyncSession, user_id: int) -> User:
    # populate_existing: đọc lại dữ liệu service vừa ghi, không lấy bản cũ trong session.
    user = await session.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    assert user is not None
    return user


def listed_ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["data"]]


# Danh sách


async def test_list_users_paginates_and_hides_deleted_users(
    client: AsyncClient, db_session: AsyncSession, admin: User, headers: dict[str, str]
) -> None:
    users = [await create_user(db_session) for _ in range(3)]
    await create_user(db_session, deleted=True)

    response = await client.get(USERS_URL, params={"page": 2, "page_size": 2}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 2, "page_size": 2, "total": 4}
    assert listed_ids(body) == [users[1].id, users[2].id]
    assert "password_hash" not in body["data"][0]
    assert "token_version" not in body["data"][0]


@pytest.mark.parametrize(
    "keyword",
    ["nguyen van an", "NGUYỄN VĂN", "  văn an  ", "an.nguyen@", "EXAMPLE.ORG"],
    ids=["no-accent", "upper-accent", "trimmed", "email-part", "email-upper"],
)
async def test_list_users_searches_name_without_accent_and_email(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], keyword: str
) -> None:
    target = await create_user(db_session, email="an.nguyen@example.org", full_name="Nguyễn Văn An")
    await create_user(db_session, email="binh@example.com", full_name="Trần Thị Bình")

    response = await client.get(USERS_URL, params={"keyword": keyword}, headers=headers)

    assert listed_ids(response.json()) == [target.id]


@pytest.mark.parametrize("keyword", ["%", "_", "\\"])
async def test_list_users_treats_like_wildcards_in_keyword_as_text(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], keyword: str
) -> None:
    await create_user(db_session, full_name="Nguyễn Văn An")
    target = await create_user(db_session, full_name=f"An {keyword} Bình")

    response = await client.get(USERS_URL, params={"keyword": keyword}, headers=headers)

    assert listed_ids(response.json()) == [target.id]


async def test_list_users_filters_by_role_and_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    dev = await create_department(db_session)
    qa = await create_department(db_session)
    target = await create_user(db_session, role=UserRole.MANAGER, department=dev)
    await create_user(db_session, role=UserRole.USER, department=dev)
    await create_user(db_session, role=UserRole.MANAGER, department=qa)

    by_role = await client.get(USERS_URL, params={"role": "MANAGER"}, headers=headers)
    both = await client.get(
        USERS_URL, params={"role": "MANAGER", "department_id": dev.id}, headers=headers
    )

    assert by_role.json()["meta"]["total"] == 2
    assert listed_ids(both.json()) == [target.id]
    assert both.json()["data"][0]["department_id"] == dev.id


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"role": "BOSS"}, "query.role"),
        ({"department_id": 0}, "query.department_id"),
        ({"keyword": "an\x00"}, "query.keyword"),
        ({"keyword": "a" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"page_size": MAX_PAGE_SIZE + 1}, "query.page_size"),
    ],
    ids=["role", "department-id", "keyword-nul", "keyword-too-long", "page-size"],
)
async def test_list_users_rejects_invalid_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(USERS_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


# Tạo


async def test_create_user_without_password(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session)
    payload = NEW_USER | {
        "phone": "0901234567",
        "date_of_birth": "1995-04-30",
        "role": "MANAGER",
        "department_id": department.id,
    }

    response = await client.post(USERS_URL, json=payload, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "binh@example.com"
    assert (body["role"], body["department_id"], body["is_active"]) == (
        "MANAGER",
        department.id,
        True,
    )
    row = await get_user_row(db_session, body["id"])
    assert (row.phone, row.date_of_birth) == ("0901234567", date(1995, 4, 30))
    # Chưa có mật khẩu: chờ user đặt qua link (S2), nên chưa đăng nhập được.
    assert row.password_hash is None


async def test_create_user_defaults_to_role_user_without_department(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post(USERS_URL, json=NEW_USER, headers=headers)

    assert response.status_code == 201
    assert (response.json()["role"], response.json()["department_id"]) == ("USER", None)


async def test_created_user_cannot_log_in_before_setting_password(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    await client.post(USERS_URL, json=NEW_USER, headers=headers)

    response = await login(client, NEW_USER["email"], DEFAULT_PASSWORD)

    assert response.status_code == 401


async def test_create_user_rejects_duplicate_email_ignoring_case(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_user(db_session, email="binh@example.com")

    response = await client.post(
        USERS_URL, json=NEW_USER | {"email": "Binh@Example.com"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_create_user_reuses_email_of_deleted_user(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_user(db_session, email="binh@example.com", deleted=True)

    response = await client.post(USERS_URL, json=NEW_USER, headers=headers)

    assert response.status_code == 201


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "deleted"])
async def test_create_user_rejects_unknown_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], deleted: bool
) -> None:
    department_id = BIGINT_MAX
    if deleted:
        department_id = (await create_department(db_session, deleted=True)).id

    response = await client.post(
        USERS_URL, json=NEW_USER | {"department_id": department_id}, headers=headers
    )

    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"field": "department_id"}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "khong-phai-email"}, "body.email"),
        ({"full_name": "  "}, "body.full_name"),
        ({"phone": "12ab"}, "body.phone"),
        ({"role": "BOSS"}, "body.role"),
        ({"department_id": BIGINT_MAX + 1}, "body.department_id"),
        ({"password": DEFAULT_PASSWORD}, "body.password"),
    ],
    ids=["email", "full-name", "phone", "role", "department-id-out-of-range", "password"],
)
async def test_create_user_rejects_invalid_body(
    client: AsyncClient, headers: dict[str, str], payload: dict[str, Any], field: str
) -> None:
    response = await client.post(USERS_URL, json=NEW_USER | payload, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


# Xem


async def test_get_user_returns_detail(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session)
    user = await create_user(db_session, email="an@example.com", department=department)

    response = await client.get(user_url(user.id), headers=headers)

    assert response.status_code == 200
    assert (response.json()["email"], response.json()["department_id"]) == (
        "an@example.com",
        department.id,
    )


@pytest.mark.parametrize("deleted", [False, True], ids=["missing", "deleted"])
async def test_get_user_returns_not_found(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], deleted: bool
) -> None:
    user_id = BIGINT_MAX
    if deleted:
        user_id = (await create_user(db_session, deleted=True)).id

    response = await client.get(user_url(user_id), headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"field": "user_id"}


@pytest.mark.parametrize("user_id", ["0", str(BIGINT_MAX + 1), "abc"])
async def test_get_user_rejects_invalid_id(
    client: AsyncClient, headers: dict[str, str], user_id: str
) -> None:
    response = await client.get(f"{USERS_URL}/{user_id}", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "path.user_id"


# Sửa


async def test_update_user_changes_only_sent_fields(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session)
    user = await create_user(db_session, email="an@example.com", full_name="Nguyễn Văn An")

    response = await client.patch(
        user_url(user.id),
        json={"email": "an.nguyen@example.com", "role": "MANAGER", "department_id": department.id},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["email"], body["full_name"], body["role"], body["department_id"]) == (
        "an.nguyen@example.com",
        "Nguyễn Văn An",
        "MANAGER",
        department.id,
    )


async def test_update_user_removes_department_with_null(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, department=await create_department(db_session))

    response = await client.patch(
        user_url(user.id), json={"department_id": None, "phone": None}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["department_id"] is None


async def test_update_user_keeps_own_email_in_other_case(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, email="an@example.com")

    response = await client.patch(
        user_url(user.id), json={"email": "An@Example.com"}, headers=headers
    )

    assert response.status_code == 200


async def test_update_user_rejects_email_of_another_user(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_user(db_session, email="binh@example.com")
    user = await create_user(db_session, email="an@example.com")

    response = await client.patch(
        user_url(user.id), json={"email": "BINH@example.com"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_update_user_rejects_deleted_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session)
    department = await create_department(db_session, deleted=True)

    response = await client.patch(
        user_url(user.id), json={"department_id": department.id}, headers=headers
    )

    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"field": "department_id"}


async def test_lock_user_ends_all_sessions(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    response = await client.patch(user_url(user.id), json={"is_active": False}, headers=headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 401
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 401


async def test_unlock_user_lets_user_log_in_again(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, email="an@example.com", is_active=False)

    response = await client.patch(user_url(user.id), json={"is_active": True}, headers=headers)

    assert response.status_code == 200
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 200


async def test_update_user_without_locking_keeps_sessions(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, email="an@example.com")
    tokens = await login_tokens(client, "an@example.com")

    await client.patch(
        user_url(user.id), json={"full_name": "Nguyễn Văn Ân", "is_active": True}, headers=headers
    )

    assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 200


@pytest.mark.parametrize(
    ("payload", "field"),
    [({"is_active": False}, "is_active"), ({"role": "USER"}, "role")],
    ids=["lock", "change-role"],
)
async def test_admin_cannot_lock_or_demote_self(
    client: AsyncClient, db_session: AsyncSession, admin: User, payload: dict[str, Any], field: str
) -> None:
    # Commit dữ liệu chuẩn bị: lỗi nghiệp vụ làm service rollback, chỉ bỏ phần service đã ghi.
    # Rollback cũng làm object hết hạn, nên lấy id trước.
    await db_session.commit()
    admin_id = admin.id

    response = await client.patch(user_url(admin_id), json=payload, headers=auth_headers(admin))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CANNOT_MODIFY_OWN_ACCOUNT"
    assert response.json()["error"]["details"] == {"field": field}
    row = await get_user_row(db_session, admin_id)
    assert (row.role, row.is_active) == (UserRole.ADMIN, True)


async def test_admin_can_update_own_profile_fields(
    client: AsyncClient, admin: User, headers: dict[str, str]
) -> None:
    response = await client.patch(
        user_url(admin.id),
        json={"full_name": "Lê Quản Trị", "role": "ADMIN", "is_active": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Lê Quản Trị"


async def test_update_user_rejects_role_change_of_manager_with_departments(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, managers=[manager])

    response = await client.patch(user_url(manager.id), json={"role": "USER"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_MANAGES_DEPARTMENTS"


async def test_update_user_allows_role_change_of_manager_of_deleted_department(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, managers=[manager], deleted=True)

    response = await client.patch(user_url(manager.id), json={"role": "USER"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["role"] == "USER"


@pytest.mark.parametrize("field", ["email", "full_name", "role", "is_active"])
async def test_update_user_rejects_null_for_required_field(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], field: str
) -> None:
    user = await create_user(db_session)

    response = await client.patch(user_url(user.id), json={field: None}, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == f"body.{field}"


async def test_update_user_rejects_unknown_field(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session)

    response = await client.patch(
        user_url(user.id), json={"password_hash": "x", "token_version": 9}, headers=headers
    )

    assert response.status_code == 422


async def test_update_user_returns_not_found_for_deleted_user(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, deleted=True)

    response = await client.patch(user_url(user.id), json={"full_name": "A"}, headers=headers)

    assert response.status_code == 404


# Xóa


async def test_delete_user_soft_deletes_and_ends_all_sessions(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    department = await create_department(db_session)
    user = await create_user(db_session, email="an@example.com", department=department)
    report = await create_report(
        db_session, author=user, department=department, report_date=date(2026, 10, 28)
    )
    tokens = await login_tokens(client, "an@example.com")

    response = await client.delete(user_url(user.id), headers=headers)

    assert response.status_code == 204
    row = await get_user_row(db_session, user.id)
    assert row.deleted_at is not None
    assert report.author_id == row.id
    assert (await client.get(user_url(user.id), headers=headers)).status_code == 404
    assert (await client.get(ME_URL, headers=bearer(tokens["access_token"]))).status_code == 401
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401
    assert (await login(client, "an@example.com", DEFAULT_PASSWORD)).status_code == 401


async def test_deleted_user_email_can_be_used_again(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session, email="binh@example.com")
    await client.delete(user_url(user.id), headers=headers)

    response = await client.post(USERS_URL, json=NEW_USER, headers=headers)

    assert response.status_code == 201


async def test_admin_cannot_delete_self(
    client: AsyncClient, db_session: AsyncSession, admin: User, headers: dict[str, str]
) -> None:
    await db_session.commit()
    admin_id = admin.id

    response = await client.delete(user_url(admin_id), headers=headers)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "CANNOT_MODIFY_OWN_ACCOUNT",
        "message": "Không thể tự khóa, tự xóa hoặc tự đổi role của tài khoản đang đăng nhập.",
        "details": None,
    }
    assert (await get_user_row(db_session, admin_id)).deleted_at is None


async def test_delete_user_rejects_manager_with_departments(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, managers=[manager])
    await db_session.commit()
    manager_id = manager.id

    response = await client.delete(user_url(manager_id), headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_MANAGES_DEPARTMENTS"
    assert (await get_user_row(db_session, manager_id)).deleted_at is None


async def test_delete_user_twice_returns_not_found(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    user = await create_user(db_session)
    await client.delete(user_url(user.id), headers=headers)

    response = await client.delete(user_url(user.id), headers=headers)

    assert response.status_code == 404


# Phân quyền, Swagger

ENDPOINTS = [
    ("GET", USERS_URL),
    ("POST", USERS_URL),
    ("GET", user_url(1)),
    ("PATCH", user_url(1)),
    ("DELETE", user_url(1)),
]


@pytest.mark.parametrize(("method", "url"), ENDPOINTS)
async def test_admin_users_endpoints_require_token(
    client: AsyncClient, method: str, url: str
) -> None:
    response = await client.request(method, url, json=NEW_USER)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MANAGER])
@pytest.mark.parametrize(("method", "url"), ENDPOINTS)
async def test_admin_users_endpoints_reject_other_roles(
    client: AsyncClient, db_session: AsyncSession, method: str, url: str, role: UserRole
) -> None:
    user = await create_user(db_session, role=role)

    response = await client.request(method, url, json=NEW_USER, headers=auth_headers(user))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("method", "path", "status_codes"),
    [
        ("get", "/admin/users", {"401", "403", "422"}),
        ("post", "/admin/users", {"401", "403", "404", "409", "422"}),
        ("get", "/admin/users/{user_id}", {"401", "403", "404", "422"}),
        ("patch", "/admin/users/{user_id}", {"400", "401", "403", "404", "409", "422"}),
        ("delete", "/admin/users/{user_id}", {"400", "401", "403", "404", "409", "422"}),
    ],
)
async def test_admin_users_endpoints_document_errors_in_swagger(
    client: AsyncClient, method: str, path: str, status_codes: set[str]
) -> None:
    response = await client.get("/openapi.json")

    responses = response.json()["paths"][f"{API}{path}"][method]["responses"]
    assert status_codes <= responses.keys()
    for status_code in status_codes:
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
