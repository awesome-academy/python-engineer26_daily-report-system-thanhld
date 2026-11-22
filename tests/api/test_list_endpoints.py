"""Endpoint trả danh sách: phân trang, số câu SQL không tăng theo số bản ghi (chống N+1).

Endpoint đọc lấy từ route của app, không liệt kê tay: route GET có kiểu trả về chứa list (trang
`Page`, list, hay object có field list như chi tiết báo cáo kèm người nhận). Endpoint mới trả danh
sách mà chưa có trong ENDPOINTS thì test đỏ. Export Excel (M5) trả file nên thêm tay.

Endpoint ghi nhận một danh sách (người nhận báo cáo, thành viên, dòng file import) cũng đếm câu
SQL theo số phần tử, ở cuối file.

Số câu của từng endpoint ghi ở docs/database.md, mục "Hiệu năng truy vấn".
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import count
from typing import Any, get_args, get_origin

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext
from httpx import AsyncClient, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router
from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import MAX_PAGE_SIZE, XLSX_MEDIA_TYPE
from app.core.pagination import Page
from app.modules.departments.models import Department, DepartmentManager
from app.modules.reports.models import ReportRecipient
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_report, create_user
from tests.helpers import (
    api_routes,
    data_queries,
    load_sheet,
    recorded_queries,
    user_import_file,
)

API = get_settings().api_v1_prefix
EXPORT_PATH = f"{API}/manager/reports/export"
# Số phần tử ở lần gọi sau, ít hơn page_size mặc định để cả danh sách nằm trong một trang.
ROWS = 5
DAY = date(2026, 3, 2)
# Tài khoản có từ trước DAY: export chỉ tính người chưa nộp đã có tài khoản trong ngày đó.
JOINED = datetime(2026, 1, 5, tzinfo=UTC)

# Danh sách không phân trang và lý do: đều bị chặn bởi số manager của một bộ phận hoặc số người
# nhận của một báo cáo, không lớn dần theo thời gian như báo cáo hay theo số nhân viên.
UNPAGED = {
    f"{API}/me/recipients": "manager của bộ phận mình, cả danh sách để chọn người nhận",
    f"{API}/me/reports/{{report_id}}": "người nhận của một báo cáo",
    f"{API}/manager/reports/{{report_id}}": "người nhận của một báo cáo",
    f"{API}/manager/departments/{{department_id}}": "manager của một bộ phận",
}


def returns_list(annotation: Any) -> bool:
    """Kiểu có chứa list ở đâu đó: list[...], Page[...], model có field list."""
    if get_origin(annotation) is list:
        return True
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return any(returns_list(info.annotation) for info in annotation.model_fields.values())
    return any(returns_list(arg) for arg in get_args(annotation))


def response_model(route: RouteContext) -> Any:
    original = route.original_route
    return original.response_model if isinstance(original, APIRoute) else None


def is_page(route: RouteContext) -> bool:
    model = response_model(route)
    return isinstance(model, type) and issubclass(model, Page)


def list_routes() -> list[RouteContext]:
    return [
        route
        for _, route in api_routes(api_router)
        if "GET" in (route.methods or ()) and returns_list(response_model(route))
    ]


def paths(routes: list[RouteContext]) -> set[str]:
    return {route.path for route in routes if route.path is not None}


PAGED_PATHS = sorted(paths([route for route in list_routes() if is_page(route)]))


# Cách gọi từng endpoint


@dataclass(frozen=True)
class ListCall:
    """Request tới một endpoint danh sách và hàm thêm một phần tử vào danh sách nó trả."""

    url: str
    headers: dict[str, str]
    add_item: Callable[[], Awaitable[None]]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListEndpoint:
    arrange: Callable[[AsyncSession], Awaitable[ListCall]]
    # Số phần tử của danh sách trong response.
    size: Callable[[Response], int]
    # Số câu SQL mỗi request, không tính SAVEPOINT của transaction test.
    queries: int


def page_items(response: Response) -> int:
    return len(response.json()["data"])


def list_items(response: Response) -> int:
    return len(response.json())


def recipient_items(response: Response) -> int:
    return len(response.json()["recipients"])


def manager_items(response: Response) -> int:
    return len(response.json()["managers"])


def sheet_items(response: Response) -> int:
    # Dòng đầu là tiêu đề.
    return len(list(load_sheet(response).iter_rows())) - 1


async def add_manager(session: AsyncSession, department: Department) -> None:
    manager = await create_user(session, role=UserRole.MANAGER)
    session.add(DepartmentManager(department_id=department.id, user_id=manager.id))
    await session.flush()


async def add_recipient(session: AsyncSession, report_id: int) -> None:
    recipient = await create_user(session, role=UserRole.MANAGER)
    session.add(ReportRecipient(report_id=report_id, recipient_id=recipient.id))
    await session.flush()


async def manager_with_department(session: AsyncSession) -> tuple[User, Department]:
    manager = await create_user(session, role=UserRole.MANAGER)
    return manager, await create_department(session, managers=[manager])


async def my_recipients(session: AsyncSession) -> ListCall:
    department = await create_department(session)
    user = await create_user(session, department=department)

    async def add_item() -> None:
        await add_manager(session, department)

    return ListCall(f"{API}/me/recipients", auth_headers(user), add_item)


async def my_reports(session: AsyncSession) -> ListCall:
    department = await create_department(session)
    user = await create_user(session, department=department)
    days = count()

    async def add_item() -> None:
        report_date = DAY - timedelta(days=next(days))
        await create_report(session, author=user, department=department, report_date=report_date)

    return ListCall(f"{API}/me/reports", auth_headers(user), add_item)


async def my_report_detail(session: AsyncSession) -> ListCall:
    department = await create_department(session)
    user = await create_user(session, department=department)
    report = await create_report(session, author=user, department=department, report_date=DAY)

    async def add_item() -> None:
        await add_recipient(session, report.id)

    return ListCall(f"{API}/me/reports/{report.id}", auth_headers(user), add_item)


async def admin_users(session: AsyncSession) -> ListCall:
    admin = await create_user(session, role=UserRole.ADMIN)
    department = await create_department(session)

    async def add_item() -> None:
        await create_user(session, department=department)

    return ListCall(f"{API}/admin/users", auth_headers(admin), add_item)


async def admin_departments(session: AsyncSession) -> ListCall:
    admin = await create_user(session, role=UserRole.ADMIN)

    async def add_item() -> None:
        await create_department(session)

    return ListCall(f"{API}/admin/departments", auth_headers(admin), add_item)


async def admin_department_members(session: AsyncSession) -> ListCall:
    admin = await create_user(session, role=UserRole.ADMIN)
    department = await create_department(session)
    added = count()

    async def add_item() -> None:
        # Xen kẽ thành viên là manager của bộ phận: cờ is_manager phải tra cho cả trang.
        role = UserRole.MANAGER if next(added) % 2 else UserRole.USER
        member = await create_user(session, role=role, department=department)
        if role is UserRole.MANAGER:
            session.add(DepartmentManager(department_id=department.id, user_id=member.id))
            await session.flush()

    return ListCall(
        f"{API}/admin/departments/{department.id}/members", auth_headers(admin), add_item
    )


async def admin_department_managers(session: AsyncSession) -> ListCall:
    admin = await create_user(session, role=UserRole.ADMIN)
    department = await create_department(session)

    async def add_item() -> None:
        await add_manager(session, department)

    return ListCall(
        f"{API}/admin/departments/{department.id}/managers", auth_headers(admin), add_item
    )


async def manager_departments(session: AsyncSession) -> ListCall:
    manager = await create_user(session, role=UserRole.MANAGER)

    async def add_item() -> None:
        await create_department(session, managers=[manager])

    return ListCall(f"{API}/manager/departments", auth_headers(manager), add_item)


async def manager_department_detail(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)

    async def add_item() -> None:
        await add_manager(session, department)
        await create_user(session, department=department)

    return ListCall(f"{API}/manager/departments/{department.id}", auth_headers(manager), add_item)


async def manager_department_members(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)

    async def add_item() -> None:
        await create_user(session, department=department)

    return ListCall(
        f"{API}/manager/departments/{department.id}/members", auth_headers(manager), add_item
    )


async def manager_candidates(session: AsyncSession) -> ListCall:
    manager = await create_user(session, role=UserRole.MANAGER)

    async def add_item() -> None:
        # Nhân viên chưa thuộc bộ phận nào.
        await create_user(session)

    return ListCall(f"{API}/manager/candidates", auth_headers(manager), add_item)


async def manager_employees(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)

    async def add_item() -> None:
        await create_user(session, department=department)

    return ListCall(f"{API}/manager/employees", auth_headers(manager), add_item)


async def manager_reports(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)

    async def add_item() -> None:
        author = await create_user(session, department=department)
        await create_report(session, author=author, department=department, report_date=DAY)

    return ListCall(f"{API}/manager/reports", auth_headers(manager), add_item)


async def manager_report_detail(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)
    author = await create_user(session, department=department)
    report = await create_report(session, author=author, department=department, report_date=DAY)

    async def add_item() -> None:
        await add_recipient(session, report.id)

    return ListCall(f"{API}/manager/reports/{report.id}", auth_headers(manager), add_item)


async def manager_export(session: AsyncSession) -> ListCall:
    manager, department = await manager_with_department(session)
    added = count()

    async def add_item() -> None:
        # Xen kẽ người đã nộp và người chưa nộp: file ghép cả hai nhánh của câu truy vấn.
        author = await create_user(session, department=department, created_at=JOINED)
        if next(added) % 2:
            await create_report(session, author=author, department=department, report_date=DAY)

    return ListCall(EXPORT_PATH, auth_headers(manager), add_item, {"date": DAY.isoformat()})


# Số câu: user đăng nhập 1, kiểm tra bộ phận trên URL 1, đếm 1, trang 1, cờ hay danh sách kèm 1.
ENDPOINTS = {
    f"{API}/me/recipients": ListEndpoint(my_recipients, list_items, queries=2),
    f"{API}/me/reports": ListEndpoint(my_reports, page_items, queries=3),
    f"{API}/me/reports/{{report_id}}": ListEndpoint(my_report_detail, recipient_items, queries=3),
    f"{API}/admin/users": ListEndpoint(admin_users, page_items, queries=3),
    f"{API}/admin/departments": ListEndpoint(admin_departments, page_items, queries=3),
    f"{API}/admin/departments/{{department_id}}/members": ListEndpoint(
        admin_department_members, page_items, queries=5
    ),
    f"{API}/admin/departments/{{department_id}}/managers": ListEndpoint(
        admin_department_managers, page_items, queries=4
    ),
    f"{API}/manager/departments": ListEndpoint(manager_departments, page_items, queries=3),
    f"{API}/manager/departments/{{department_id}}": ListEndpoint(
        manager_department_detail, manager_items, queries=4
    ),
    f"{API}/manager/departments/{{department_id}}/members": ListEndpoint(
        manager_department_members, page_items, queries=5
    ),
    f"{API}/manager/candidates": ListEndpoint(manager_candidates, page_items, queries=3),
    f"{API}/manager/employees": ListEndpoint(manager_employees, page_items, queries=3),
    f"{API}/manager/reports": ListEndpoint(manager_reports, page_items, queries=3),
    f"{API}/manager/reports/{{report_id}}": ListEndpoint(
        manager_report_detail, recipient_items, queries=3
    ),
    EXPORT_PATH: ListEndpoint(manager_export, sheet_items, queries=2),
}


def test_every_list_endpoint_has_a_query_count_case() -> None:
    discovered = paths(list_routes())

    # Cách tìm route sai thì các test dưới chỉ chạy phần thêm tay mà vẫn xanh.
    assert len(discovered) > len(UNPAGED)
    assert discovered | {EXPORT_PATH} == set(ENDPOINTS)


def test_lists_are_paginated_unless_bounded() -> None:
    unpaged = paths([route for route in list_routes() if not is_page(route)])

    assert unpaged == set(UNPAGED)


@pytest.mark.parametrize("path", PAGED_PATHS, ids=lambda path: path.removeprefix(API))
async def test_page_size_is_capped(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    call = await ENDPOINTS[path].arrange(db_session)

    response = await client.get(
        call.url, params={**call.params, "page_size": MAX_PAGE_SIZE + 1}, headers=call.headers
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["query.page_size"]


@pytest.mark.parametrize("path", sorted(ENDPOINTS), ids=lambda path: path.removeprefix(API))
async def test_query_count_does_not_grow_with_rows(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    endpoint = ENDPOINTS[path]
    call = await endpoint.arrange(db_session)
    await call.add_item()
    with recorded_queries(db_session) as one_row:
        first = await client.get(call.url, params=call.params, headers=call.headers)
    for _ in range(ROWS - 1):
        await call.add_item()

    with recorded_queries(db_session) as many_rows:
        second = await client.get(call.url, params=call.params, headers=call.headers)

    assert (first.status_code, second.status_code) == (200, 200)
    assert endpoint.size(second) - endpoint.size(first) == ROWS - 1
    assert len(data_queries(one_row)) == len(data_queries(many_rows)) == endpoint.queries


# Endpoint ghi nhận một danh sách


async def test_create_report_query_count_does_not_grow_with_recipients(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    app.dependency_overrides[local_today] = lambda: DAY
    managers = [await create_user(db_session, role=UserRole.MANAGER) for _ in range(ROWS)]
    department = await create_department(db_session, managers=managers)
    author = await create_user(db_session, department=department, created_at=JOINED)
    headers = auth_headers(author)

    async def create(report_date: date, recipients: list[User]) -> list[tuple[str, Any]]:
        body = {
            "report_date": report_date.isoformat(),
            "planned_work": "Làm API",
            "actual_work": "Xong API",
            "next_day_plan": "Viết test",
            "recipient_ids": [recipient.id for recipient in recipients],
        }
        with recorded_queries(db_session) as queries:
            response = await client.post(f"{API}/me/reports", json=body, headers=headers)
        assert response.status_code == 201
        assert len(response.json()["recipients"]) == len(recipients)
        return queries

    one = await create(DAY - timedelta(days=1), managers[:1])
    many = await create(DAY, managers)

    # User đăng nhập, trùng ngày, danh sách người nhận, thêm báo cáo, thêm người nhận (executemany).
    assert len(data_queries(one)) == len(data_queries(many)) == 5


async def test_add_members_query_count_does_not_grow_with_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    manager, department = await manager_with_department(db_session)
    candidates = [await create_user(db_session) for _ in range(ROWS + 1)]
    url = f"{API}/manager/departments/{department.id}/members"

    async def add(users: list[User]) -> list[tuple[str, Any]]:
        body = {"user_ids": [user.id for user in users]}
        with recorded_queries(db_session) as queries:
            response = await client.post(url, json=body, headers=auth_headers(manager))
        assert response.status_code == 204
        return queries

    one = await add(candidates[:1])
    many = await add(candidates[1:])

    # User đăng nhập, khóa bộ phận, khóa các user, UPDATE (executemany).
    assert len(data_queries(one)) == len(data_queries(many)) == 4


async def test_import_query_count_does_not_grow_with_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(await create_user(db_session, role=UserRole.ADMIN))
    department = await create_department(db_session)

    async def upload(emails: list[str]) -> list[tuple[str, Any]]:
        data = user_import_file(
            *([email, "Nguyễn Văn An", None, None, department.code, None] for email in emails)
        )
        with recorded_queries(db_session) as queries:
            response = await client.post(
                f"{API}/admin/users/import",
                files={"file": ("nhan-vien.xlsx", data, XLSX_MEDIA_TYPE)},
                headers=headers,
            )
        assert response.status_code == 201
        assert response.json()["created_count"] == len(emails)
        return queries

    one = await upload(["mot@example.com"])
    many = await upload([f"nhieu{index}@example.com" for index in range(ROWS)])

    # User đăng nhập, khóa bộ phận theo mã, email đã có, INSERT nhiều dòng trong một câu.
    assert len(data_queries(one)) == len(data_queries(many)) == 4
