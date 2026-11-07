"""Manager xem báo cáo của nhân viên bộ phận mình quản lý (M3).

Bộ lọc `department_id` ngoài phạm vi (bộ phận khác, đã xóa, role sai, id sai) chạy theo ma trận
quyền ở tests/api/test_department_scope.py; ở đây là dữ liệu trả về.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import BIGINT_MAX, DEFAULT_PAGE_SIZE, KEYWORD_MAX_LENGTH, MAX_PAGE_SIZE
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.models import Department
from app.modules.reports.exceptions import ReportNotFoundError
from app.modules.reports.models import DailyReport
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_report, create_user
from tests.helpers import error_json, recorded_queries

API = get_settings().api_v1_prefix
REPORTS_URL = f"{API}/manager/reports"
DAY_1 = date(2026, 3, 2)
DAY_2 = date(2026, 3, 3)
DAY_3 = date(2026, 3, 4)


def report_url(report_id: int) -> str:
    return f"{REPORTS_URL}/{report_id}"


def ids_of(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["data"]]


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, full_name="Quản Lý", role=UserRole.MANAGER)


@pytest.fixture
def headers(manager: User) -> dict[str, str]:
    return auth_headers(manager)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, managers=[manager])


async def write(
    session: AsyncSession, department: Department, report_date: date, **author_fields: Any
) -> DailyReport:
    """Báo cáo của một nhân viên mới trong `department`."""
    author = await create_user(session, department=department, **author_fields)
    return await create_report(
        session, author=author, department=department, report_date=report_date
    )


# Danh sách


async def test_manager_lists_reports_of_managed_departments_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    second = await create_department(db_session, managers=[manager])
    author = await create_user(db_session, full_name="Trần Bình", department=department)
    older = await create_report(db_session, author=author, department=department, report_date=DAY_1)
    newer = await write(db_session, second, DAY_2, full_name="Lê An")
    same_day = await write(db_session, department, DAY_2, full_name="Đặng Cường")
    # Ngoài phạm vi: bộ phận người khác quản lý, bộ phận manager chỉ là thành viên, bộ phận đã xóa.
    await write(db_session, await create_department(db_session), DAY_3)
    member_only = await create_department(db_session)
    manager.department_id = member_only.id
    await write(db_session, member_only, DAY_3)
    deleted = await create_department(db_session, managers=[manager], deleted=True)
    await write(db_session, deleted, DAY_3)

    response = await client.get(REPORTS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    # Cùng ngày thì sắp theo tên người viết (không dấu): "Đặng" trước "Lê".
    assert ids_of(body) == [same_day.id, newer.id, older.id]
    assert body["meta"] == {"page": 1, "page_size": DEFAULT_PAGE_SIZE, "total": 3}
    item = body["data"][2]
    assert item["department_id"] == department.id
    assert item["report_date"] == DAY_1.isoformat()
    assert item["planned_work"] == older.planned_work
    assert item["incomplete_reason"] is None
    assert item["author"] == {
        "id": author.id,
        "full_name": "Trần Bình",
        "email": author.email,
        "is_deleted": False,
    }


async def test_manager_without_departments_gets_empty_list(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await write(db_session, await create_department(db_session), DAY_1)

    response = await client.get(REPORTS_URL, headers=headers)

    assert response.json() == {
        "data": [],
        "meta": {"page": 1, "page_size": DEFAULT_PAGE_SIZE, "total": 0},
    }


async def test_reports_follow_department_at_writing_time(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    # Nhân viên chuyển từ bộ phận mình sang bộ phận khác: báo cáo cũ vẫn thuộc phạm vi, báo cáo
    # viết ở bộ phận mới thì không. Người chuyển vào: báo cáo viết ở bộ phận cũ không hiện.
    other = await create_department(db_session)
    moved_out = await create_user(db_session, department=other)
    before_move = await create_report(
        db_session, author=moved_out, department=department, report_date=DAY_1
    )
    await create_report(db_session, author=moved_out, department=other, report_date=DAY_2)
    moved_in = await create_user(db_session, department=department)
    await create_report(db_session, author=moved_in, department=other, report_date=DAY_1)

    response = await client.get(REPORTS_URL, headers=headers)

    assert ids_of(response.json()) == [before_move.id]


async def test_list_includes_reports_of_locked_and_deleted_authors(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    # Báo cáo giữ lại khi khóa, xóa tài khoản. Email người đã xóa có thể thuộc tài khoản mới.
    locked = await write(db_session, department, DAY_2, full_name="An", is_active=False)
    deleted = await write(db_session, department, DAY_1, full_name="Bình", deleted=True)

    response = await client.get(REPORTS_URL, headers=headers)

    data = response.json()["data"]
    assert [item["id"] for item in data] == [locked.id, deleted.id]
    assert data[0]["author"]["is_deleted"] is False
    assert data[1]["author"] == {
        "id": deleted.author_id,
        "full_name": "Bình",
        "email": None,
        "is_deleted": True,
    }


@pytest.fixture
async def reports_on_three_days(
    db_session: AsyncSession, department: Department
) -> list[DailyReport]:
    return [await write(db_session, department, day) for day in (DAY_1, DAY_2, DAY_3)]


@pytest.mark.parametrize(
    ("params", "expected_days"),
    [
        ({"date_from": DAY_2.isoformat()}, [DAY_3, DAY_2]),
        ({"date_to": DAY_2.isoformat()}, [DAY_2, DAY_1]),
        ({"date_from": DAY_2.isoformat(), "date_to": DAY_2.isoformat()}, [DAY_2]),
        ({"date_from": DAY_1.isoformat(), "date_to": DAY_3.isoformat()}, [DAY_3, DAY_2, DAY_1]),
    ],
    ids=["from", "to", "single-day", "both-ends-inclusive"],
)
@pytest.mark.usefixtures("reports_on_three_days")
async def test_manager_filters_reports_by_date_range(
    client: AsyncClient,
    headers: dict[str, str],
    params: dict[str, str],
    expected_days: list[date],
) -> None:
    response = await client.get(REPORTS_URL, params=params, headers=headers)

    assert [item["report_date"] for item in response.json()["data"]] == [
        day.isoformat() for day in expected_days
    ]


async def test_manager_filters_reports_by_managed_department(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    second = await create_department(db_session, managers=[manager])
    wanted = await write(db_session, second, DAY_1)
    await write(db_session, department, DAY_2)

    response = await client.get(REPORTS_URL, params={"department_id": second.id}, headers=headers)

    assert ids_of(response.json()) == [wanted.id]


async def test_manager_searches_reports_by_author_name_without_accents(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    first = await write(db_session, department, DAY_2, full_name="Nguyễn Văn An")
    second = await write(db_session, department, DAY_1, full_name="NGUYỄN THỊ BÌNH")
    await write(db_session, department, DAY_3, full_name="Trần Cường", email="nguyen@example.com")

    response = await client.get(REPORTS_URL, params={"keyword": " nguyen "}, headers=headers)

    # Chỉ tìm theo họ tên: "Trần Cường" có email chứa "nguyen" nhưng không khớp.
    assert ids_of(response.json()) == [first.id, second.id]


async def test_author_search_stays_within_scope(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    mine = await write(db_session, department, DAY_1, full_name="Nguyễn An")
    await write(db_session, await create_department(db_session), DAY_1, full_name="Nguyễn An")

    response = await client.get(REPORTS_URL, params={"keyword": "nguyen"}, headers=headers)

    assert ids_of(response.json()) == [mine.id]


@pytest.mark.parametrize("keyword", ["%", "_", "\\", "\uff05"])
async def test_author_search_treats_like_wildcards_as_text(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    department: Department,
    keyword: str,
) -> None:
    # % full-width thành % thường sau unaccent, vẫn phải được escape.
    target = await write(db_session, department, DAY_1, full_name="An % _ \\ Bình")
    await write(db_session, department, DAY_2, full_name="Cường")

    response = await client.get(REPORTS_URL, params={"keyword": keyword}, headers=headers)

    assert ids_of(response.json()) == [target.id]


async def test_blank_keyword_does_not_filter(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    await write(db_session, department, DAY_1)
    await write(db_session, department, DAY_2)

    response = await client.get(REPORTS_URL, params={"keyword": "   "}, headers=headers)

    assert response.json()["meta"]["total"] == 2


@pytest.fixture
async def reports_to_sort(db_session: AsyncSession, department: Department) -> None:
    # Cùng ngày thì sắp theo tên; cùng tên thì ngày mới trước. Tên sắp không dấu, không phân biệt
    # hoa thường (collation của DB sắp theo byte: "Bình" trước "an").
    await write(db_session, department, DAY_2, full_name="an")
    await write(db_session, department, DAY_1, full_name="Ánh")
    binh = await create_user(db_session, department=department, full_name="Bình")
    for day in (DAY_1, DAY_2):
        await create_report(db_session, author=binh, department=department, report_date=day)


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        (None, [("an", DAY_2), ("Bình", DAY_2), ("Ánh", DAY_1), ("Bình", DAY_1)]),
        ("-report_date", [("an", DAY_2), ("Bình", DAY_2), ("Ánh", DAY_1), ("Bình", DAY_1)]),
        ("report_date", [("Ánh", DAY_1), ("Bình", DAY_1), ("an", DAY_2), ("Bình", DAY_2)]),
        ("author_name", [("an", DAY_2), ("Ánh", DAY_1), ("Bình", DAY_2), ("Bình", DAY_1)]),
        ("-author_name", [("Bình", DAY_2), ("Bình", DAY_1), ("Ánh", DAY_1), ("an", DAY_2)]),
    ],
    ids=["default", "newest-first", "oldest-first", "author-name", "author-name-desc"],
)
@pytest.mark.usefixtures("reports_to_sort")
async def test_manager_sorts_reports(
    client: AsyncClient,
    headers: dict[str, str],
    sort: str | None,
    expected: list[tuple[str, date]],
) -> None:
    params = {"sort": sort} if sort else {}

    response = await client.get(REPORTS_URL, params=params, headers=headers)

    data = response.json()["data"]
    assert [
        (item["author"]["full_name"], date.fromisoformat(item["report_date"])) for item in data
    ] == expected


async def test_manager_lists_reports_paginated(
    client: AsyncClient, headers: dict[str, str], reports_on_three_days: list[DailyReport]
) -> None:
    response = await client.get(REPORTS_URL, params={"page": 2, "page_size": 2}, headers=headers)

    body = response.json()
    assert ids_of(body) == [reports_on_three_days[0].id]
    assert body["meta"] == {"page": 2, "page_size": 2, "total": 3}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"page": 0}, "query.page"),
        ({"page_size": MAX_PAGE_SIZE + 1}, "query.page_size"),
        ({"sort": "created_at"}, "query.sort"),
        ({"date_from": "2026-02-30"}, "query.date_from"),
        ({"date_from": DAY_2.isoformat(), "date_to": DAY_1.isoformat()}, "query.date_to"),
        ({"keyword": "k" * (KEYWORD_MAX_LENGTH + 1)}, "query.keyword"),
        ({"keyword": "k\x00"}, "query.keyword"),
    ],
    ids=[
        "page-zero",
        "page-size-too-large",
        "unknown-sort",
        "invalid-date",
        "date-to-before-date-from",
        "keyword-too-long",
        "keyword-with-nul",
    ],
)
async def test_list_reports_validates_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(REPORTS_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


async def test_query_is_validated_before_department_scope(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    # Thứ tự lỗi trong api-design: 422 tham số trước 404 phạm vi.
    other = await create_department(db_session)

    response = await client.get(
        REPORTS_URL, params={"page": 0, "department_id": other.id}, headers=headers
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["query.page"]


async def test_report_list_query_count_does_not_grow_with_page_size(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    large = await create_department(db_session, managers=[manager])
    await write(db_session, department, DAY_1)
    for day in (DAY_1, DAY_2, DAY_3):
        await write(db_session, large, day)
        await write(db_session, large, day)

    with recorded_queries(db_session) as small_queries:
        small = await client.get(
            REPORTS_URL, params={"department_id": department.id}, headers=headers
        )
    with recorded_queries(db_session) as large_queries:
        big = await client.get(REPORTS_URL, params={"department_id": large.id}, headers=headers)

    assert small.json()["meta"]["total"] == 1
    assert big.json()["meta"]["total"] == 6
    assert len(large_queries) == len(small_queries)


# Chi tiết


async def test_manager_views_report_with_author_department_and_recipients(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    author = await create_user(db_session, full_name="Nguyễn Văn An", department=department)
    other_manager = await create_user(db_session, role=UserRole.MANAGER, full_name="Bình")
    report = await create_report(
        db_session,
        author=author,
        department=department,
        report_date=DAY_1,
        recipients=[other_manager, manager],
    )

    response = await client.get(report_url(report.id), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["report_date"]) == (report.id, DAY_1.isoformat())
    assert body["actual_work"] == report.actual_work
    assert body["author"] == {
        "id": author.id,
        "full_name": "Nguyễn Văn An",
        "email": author.email,
        "is_deleted": False,
    }
    assert body["department"] == {
        "id": department.id,
        "code": department.code,
        "name": department.name,
    }
    assert [r["full_name"] for r in body["recipients"]] == ["Bình", "Quản Lý"]


async def test_manager_views_report_not_addressed_to_them(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    # Phạm vi theo bộ phận, không theo người nhận: báo cáo viết trước khi manager được gán, hoặc
    # nhân viên bỏ chọn manager này, vẫn xem được.
    report = await write(db_session, department, DAY_1)

    response = await client.get(report_url(report.id), headers=headers)

    assert response.status_code == 200
    assert response.json()["recipients"] == []


async def test_report_detail_hides_email_of_deleted_author(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    report = await write(db_session, department, DAY_1, full_name="Bình", deleted=True)

    response = await client.get(report_url(report.id), headers=headers)

    assert response.json()["author"] == {
        "id": report.author_id,
        "full_name": "Bình",
        "email": None,
        "is_deleted": True,
    }


# Tạo một báo cáo theo kịch bản, trả id; manager là người gọi API.
ArrangeReport = Callable[[AsyncSession, User], Awaitable[int]]


async def _report_of_other_department(session: AsyncSession, manager: User) -> int:
    return (await write(session, await create_department(session), DAY_1)).id


async def _report_of_department_manager_only_belongs_to(
    session: AsyncSession, manager: User
) -> int:
    department = await create_department(session)
    manager.department_id = department.id
    return (await write(session, department, DAY_1)).id


async def _report_of_deleted_department(session: AsyncSession, manager: User) -> int:
    department = await create_department(session, managers=[manager], deleted=True)
    return (await write(session, department, DAY_1)).id


async def _report_moved_out_with_author(session: AsyncSession, manager: User) -> int:
    # Nhân viên đang thuộc bộ phận mình, nhưng báo cáo viết khi còn ở bộ phận khác.
    managed = await create_department(session, managers=[manager])
    other = await create_department(session)
    author = await create_user(session, department=managed)
    report = await create_report(session, author=author, department=other, report_date=DAY_1)
    return report.id


async def _missing_report(session: AsyncSession, manager: User) -> int:
    return BIGINT_MAX


@pytest.mark.parametrize(
    "arrange",
    [
        _report_of_other_department,
        _report_of_department_manager_only_belongs_to,
        _report_of_deleted_department,
        _report_moved_out_with_author,
        _missing_report,
    ],
    ids=["other-department", "member-only", "deleted-department", "written-elsewhere", "missing"],
)
async def test_report_outside_scope_is_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    arrange: ArrangeReport,
) -> None:
    report_id = await arrange(db_session, manager)

    response = await client.get(report_url(report_id), headers=headers)

    assert response.status_code == 404
    assert response.json() == error_json(ReportNotFoundError())


@pytest.mark.parametrize("report_id", ["0", str(BIGINT_MAX + 1), "abc"])
async def test_get_report_rejects_invalid_id(
    client: AsyncClient, headers: dict[str, str], report_id: str
) -> None:
    response = await client.get(f"{REPORTS_URL}/{report_id}", headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["path.report_id"]


# Phân quyền, Swagger


@pytest.mark.parametrize("path", ["", "/1"], ids=["list", "detail"])
@pytest.mark.parametrize(
    ("role", "error"),
    [
        (None, UnauthorizedError()),
        (UserRole.USER, ForbiddenError()),
        (UserRole.ADMIN, ForbiddenError()),
    ],
    ids=["anonymous", "user", "admin"],
)
async def test_report_endpoints_require_manager_role(
    client: AsyncClient,
    db_session: AsyncSession,
    path: str,
    role: UserRole | None,
    error: AppError,
) -> None:
    caller = await create_user(db_session, role=role) if role else None
    # Có liên kết manager (dữ liệu cũ) cũng không được xem khi role không phải MANAGER.
    await create_department(db_session, managers=[caller] if caller else [])

    response = await client.get(
        f"{REPORTS_URL}{path}", headers=auth_headers(caller) if caller else {}
    )

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


@pytest.mark.parametrize("path", ["/manager/reports", "/manager/reports/{report_id}"])
async def test_endpoints_document_errors_in_swagger(client: AsyncClient, path: str) -> None:
    response = await client.get("/openapi.json")

    responses = response.json()["paths"][f"{API}{path}"]["get"]["responses"]
    for status_code in ("401", "403", "404", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
