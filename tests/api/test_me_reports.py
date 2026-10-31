from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import (
    BIGINT_MAX,
    DEFAULT_PAGE_SIZE,
    REPORT_BACKDATE_DAYS,
    REPORT_CONTENT_MAX_LENGTH,
    REPORT_RECIPIENTS_MAX,
)
from app.modules.departments.models import Department
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_report, create_user

API = get_settings().api_v1_prefix
RECIPIENTS_URL = f"{API}/me/recipients"
REPORTS_URL = f"{API}/me/reports"
# Ngày 1/3 năm không nhuận: lùi 3 ngày là sang tháng 2, thử luôn mốc qua tháng.
TODAY = date(2026, 3, 1)
# Tài khoản người viết tạo từ trước, không chặn ngày báo cáo nào trong các test.
JOINED = datetime(2026, 1, 1, tzinfo=UTC)


def report_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "report_date": TODAY.isoformat(),
        "planned_work": "Làm API báo cáo",
        "actual_work": "Xong API tạo báo cáo",
        "next_day_plan": "Làm lịch sử báo cáo",
    }
    body.update(overrides)
    return body


def error_of(body: dict[str, Any]) -> tuple[str, Any]:
    return body["error"]["code"], body["error"]["details"]


async def count_reports(session: AsyncSession, author: User) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(DailyReport).where(DailyReport.author_id == author.id)
        )
        or 0
    )


@pytest.fixture(autouse=True)
def fixed_today(app: FastAPI) -> None:
    app.dependency_overrides[local_today] = lambda: TODAY


@pytest.fixture
async def managers(db_session: AsyncSession) -> list[User]:
    # Tạo theo thứ tự ngược tên để kiểm tra danh sách được sắp theo tên.
    return [
        await create_user(db_session, role=UserRole.MANAGER, full_name=name)
        for name in ("Trần Thị Bình", "Lê Văn Cường")
    ]


@pytest.fixture
async def department(db_session: AsyncSession, managers: list[User]) -> Department:
    return await create_department(db_session, managers=managers)


@pytest.fixture
async def author(db_session: AsyncSession, department: Department) -> User:
    return await create_user(db_session, department=department, created_at=JOINED)


@pytest.fixture
def headers(author: User) -> dict[str, str]:
    return auth_headers(author)


# Phân quyền: chỉ role USER viết báo cáo (Q3).


@pytest.mark.parametrize(("method", "url"), [("GET", RECIPIENTS_URL), ("POST", REPORTS_URL)])
async def test_report_endpoints_require_login(client: AsyncClient, method: str, url: str) -> None:
    response = await client.request(method, url)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
async def test_non_user_role_cannot_write_reports(
    client: AsyncClient, db_session: AsyncSession, department: Department, role: UserRole
) -> None:
    user = await create_user(db_session, role=role, department=department)

    responses = [
        await client.get(RECIPIENTS_URL, headers=auth_headers(user)),
        await client.post(REPORTS_URL, json=report_body(), headers=auth_headers(user)),
    ]

    assert [r.status_code for r in responses] == [403, 403]
    assert await count_reports(db_session, user) == 0


# Danh sách người nhận


async def test_recipients_are_active_managers_of_own_department_sorted_by_name(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    managers: list[User],
    headers: dict[str, str],
) -> None:
    other_manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, managers=[other_manager])

    response = await client.get(RECIPIENTS_URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {"id": user.id, "full_name": user.full_name, "email": user.email}
        for user in (managers[1], managers[0])
    ]


async def test_recipients_are_sorted_by_name_ignoring_case_and_accents(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Collation của DB (image alpine) sắp theo byte: chữ thường, chữ có dấu đứng sau "Z".
    names = ["Zung", "Bình", "an", "Ánh"]
    managers = [await create_user(db_session, role=UserRole.MANAGER, full_name=n) for n in names]
    department = await create_department(db_session, managers=managers)
    author = await create_user(db_session, department=department)

    response = await client.get(RECIPIENTS_URL, headers=auth_headers(author))

    assert [r["full_name"] for r in response.json()] == ["an", "Ánh", "Bình", "Zung"]


@pytest.mark.parametrize(
    "change",
    [{"is_active": False}, {"deleted": True}, {"password": None}, {"role": UserRole.USER}],
    ids=["locked", "deleted", "password-not-set", "no-longer-manager"],
)
async def test_recipients_exclude_managers_who_cannot_receive(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], change: dict[str, Any]
) -> None:
    # Liên kết manager vẫn còn: khóa, xóa mềm, đổi role user không tự gỡ liên kết.
    user = await create_user(db_session, **{"role": UserRole.MANAGER, **change})
    department = await create_department(db_session, managers=[user])
    author = await create_user(db_session, department=department)

    response = await client.get(RECIPIENTS_URL, headers=auth_headers(author))

    assert response.status_code == 200
    assert response.json() == []


async def test_user_without_department_has_no_recipients(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_user(db_session)

    response = await client.get(RECIPIENTS_URL, headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json() == []


# Tạo báo cáo


async def test_create_report_sends_to_all_managers_by_default(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    department: Department,
    managers: list[User],
) -> None:
    response = await client.post(
        REPORTS_URL,
        json=report_body(
            planned_work="  Làm API báo cáo  ", incomplete_reason="Chờ review", next_day_plan="Test"
        ),
        headers=auth_headers(author),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["report_date"] == TODAY.isoformat()
    assert body["department_id"] == department.id
    assert body["planned_work"] == "Làm API báo cáo"
    assert body["incomplete_reason"] == "Chờ review"
    assert [r["id"] for r in body["recipients"]] == [managers[1].id, managers[0].id]
    assert body["created_at"]
    assert body["updated_at"]
    recipient_ids = await db_session.scalars(
        select(ReportRecipient.recipient_id).where(ReportRecipient.report_id == body["id"])
    )
    assert set(recipient_ids) == {manager.id for manager in managers}
    report = await db_session.get_one(DailyReport, body["id"])
    assert report.author_id == author.id


async def test_create_report_sends_only_to_chosen_recipients(
    client: AsyncClient, managers: list[User], headers: dict[str, str]
) -> None:
    chosen = managers[0].id

    response = await client.post(
        REPORTS_URL, json=report_body(recipient_ids=[chosen, chosen]), headers=headers
    )

    assert response.status_code == 201
    assert [r["id"] for r in response.json()["recipients"]] == [chosen]


@pytest.mark.parametrize("reason", [None, "", "   "], ids=["null", "empty", "spaces"])
async def test_create_report_stores_blank_incomplete_reason_as_null(
    client: AsyncClient, headers: dict[str, str], reason: str | None
) -> None:
    response = await client.post(
        REPORTS_URL, json=report_body(incomplete_reason=reason), headers=headers
    )

    assert response.status_code == 201
    assert response.json()["incomplete_reason"] is None


@pytest.mark.parametrize("days_ago", range(REPORT_BACKDATE_DAYS + 1))
async def test_create_report_accepts_today_and_recent_days(
    client: AsyncClient, headers: dict[str, str], days_ago: int
) -> None:
    report_date = TODAY - timedelta(days=days_ago)

    response = await client.post(
        REPORTS_URL, json=report_body(report_date=report_date.isoformat()), headers=headers
    )

    assert response.status_code == 201
    assert response.json()["report_date"] == report_date.isoformat()


@pytest.mark.parametrize(
    "report_date",
    [TODAY - timedelta(days=REPORT_BACKDATE_DAYS + 1), TODAY + timedelta(days=1)],
    ids=["too-old", "future"],
)
async def test_create_report_rejects_date_out_of_range(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    headers: dict[str, str],
    report_date: date,
) -> None:
    response = await client.post(
        REPORTS_URL, json=report_body(report_date=report_date.isoformat()), headers=headers
    )

    assert response.status_code == 422
    assert error_of(response.json()) == (
        "REPORT_DATE_OUT_OF_RANGE",
        {
            "field": "report_date",
            "min_date": (TODAY - timedelta(days=REPORT_BACKDATE_DAYS)).isoformat(),
            "max_date": TODAY.isoformat(),
        },
    )
    assert await count_reports(db_session, author) == 0


async def test_create_report_rejects_date_before_account_was_created(
    client: AsyncClient, db_session: AsyncSession, department: Department
) -> None:
    # 01:00 ngày 28/2 giờ nghiệp vụ, theo UTC vẫn là 27/2: ngày tạo tính theo giờ nghiệp vụ.
    joined = datetime(2026, 2, 28, 1, tzinfo=ZoneInfo(get_settings().timezone))
    newcomer = await create_user(db_session, department=department, created_at=joined)
    headers = auth_headers(newcomer)

    rejected = await client.post(
        REPORTS_URL, json=report_body(report_date="2026-02-27"), headers=headers
    )
    accepted = await client.post(
        REPORTS_URL, json=report_body(report_date="2026-02-28"), headers=headers
    )

    assert rejected.status_code == 422
    assert error_of(rejected.json()) == (
        "REPORT_DATE_OUT_OF_RANGE",
        {"field": "report_date", "min_date": "2026-02-28", "max_date": TODAY.isoformat()},
    )
    assert accepted.status_code == 201


async def test_create_report_uses_business_timezone_today(
    app: FastAPI, client: AsyncClient, headers: dict[str, str]
) -> None:
    # Bỏ ngày cố định: router lấy hôm nay từ local_today().
    del app.dependency_overrides[local_today]

    response = await client.post(
        REPORTS_URL, json=report_body(report_date=local_today().isoformat()), headers=headers
    )

    assert response.status_code == 201


async def test_create_report_rejects_second_report_for_same_date(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    department: Department,
    headers: dict[str, str],
) -> None:
    await create_report(db_session, author=author, department=department, report_date=TODAY)

    response = await client.post(REPORTS_URL, json=report_body(), headers=headers)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "REPORT_ALREADY_EXISTS",
        "message": f"Bạn đã tạo báo cáo cho ngày {TODAY.isoformat()}.",
        "details": {"field": "report_date"},
    }
    assert await count_reports(db_session, author) == 1


async def test_same_date_is_free_for_other_users_and_other_dates(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    department: Department,
    headers: dict[str, str],
) -> None:
    colleague = await create_user(db_session, department=department)
    await create_report(db_session, author=colleague, department=department, report_date=TODAY)
    yesterday = TODAY - timedelta(days=1)
    await create_report(db_session, author=author, department=department, report_date=yesterday)

    response = await client.post(REPORTS_URL, json=report_body(), headers=headers)

    assert response.status_code == 201


async def test_create_report_rejects_recipients_outside_own_department(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    department: Department,
    managers: list[User],
) -> None:
    other_manager = await create_user(db_session, role=UserRole.MANAGER)
    await create_department(db_session, managers=[other_manager])
    locked_manager = await create_user(db_session, role=UserRole.MANAGER, is_active=False)
    await create_department(db_session, managers=[locked_manager])
    colleague = await create_user(db_session, department=department)
    invalid_ids = [other_manager.id, locked_manager.id, colleague.id, author.id, BIGINT_MAX]

    response = await client.post(
        REPORTS_URL,
        json=report_body(recipient_ids=[managers[0].id, *invalid_ids]),
        headers=auth_headers(author),
    )

    assert response.status_code == 422
    assert error_of(response.json()) == (
        "INVALID_RECIPIENT",
        {"field": "recipient_ids", "invalid_ids": invalid_ids},
    )
    assert await count_reports(db_session, author) == 0


async def test_create_report_rejects_locked_manager_of_own_department(
    client: AsyncClient, db_session: AsyncSession, managers: list[User], headers: dict[str, str]
) -> None:
    managers[0].is_active = False
    await db_session.flush()

    response = await client.post(
        REPORTS_URL, json=report_body(recipient_ids=[managers[0].id]), headers=headers
    )

    assert response.status_code == 422
    assert error_of(response.json()) == (
        "INVALID_RECIPIENT",
        {"field": "recipient_ids", "invalid_ids": [managers[0].id]},
    )


@pytest.mark.parametrize("has_department", [False, True], ids=["no-department", "no-manager"])
async def test_create_report_requires_someone_to_receive_it(
    client: AsyncClient, db_session: AsyncSession, has_department: bool
) -> None:
    department = await create_department(db_session) if has_department else None
    user = await create_user(db_session, department=department, created_at=JOINED)

    response = await client.post(REPORTS_URL, json=report_body(), headers=auth_headers(user))

    assert response.status_code == 422
    assert error_of(response.json()) == ("NO_RECIPIENT_AVAILABLE", None)
    assert await count_reports(db_session, user) == 0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"report_date": None}, "body.report_date"),
        ({"report_date": "09/11/2026"}, "body.report_date"),
        ({"planned_work": "   "}, "body.planned_work"),
        ({"actual_work": "x" * (REPORT_CONTENT_MAX_LENGTH + 1)}, "body.actual_work"),
        ({"next_day_plan": None}, "body.next_day_plan"),
        ({"next_day_plan": "a\x00b"}, "body.next_day_plan"),
        ({"incomplete_reason": "a\x00b"}, "body.incomplete_reason"),
        ({"incomplete_reason": "x" * (REPORT_CONTENT_MAX_LENGTH + 1)}, "body.incomplete_reason"),
        ({"recipient_ids": []}, "body.recipient_ids"),
        ({"recipient_ids": [0]}, "body.recipient_ids.0"),
        ({"recipient_ids": [BIGINT_MAX + 1]}, "body.recipient_ids.0"),
        ({"recipient_ids": list(range(1, REPORT_RECIPIENTS_MAX + 2))}, "body.recipient_ids"),
        ({"author_id": 1}, "body.author_id"),
    ],
    ids=[
        "date-null",
        "date-format",
        "blank-content",
        "content-too-long",
        "content-null",
        "content-nul",
        "reason-nul",
        "reason-too-long",
        "no-recipient",
        "recipient-id-zero",
        "recipient-id-over-bigint",
        "too-many-recipients",
        "unknown-field",
    ],
)
async def test_create_report_validates_body(
    client: AsyncClient,
    db_session: AsyncSession,
    author: User,
    overrides: dict[str, Any],
    field: str,
) -> None:
    response = await client.post(
        REPORTS_URL, json=report_body(**overrides), headers=auth_headers(author)
    )

    assert response.status_code == 422
    code, details = error_of(response.json())
    assert code == "VALIDATION_ERROR"
    assert field in [item["field"] for item in details]
    assert await count_reports(db_session, author) == 0


async def test_create_report_requires_every_content_field(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post(REPORTS_URL, json={}, headers=headers)

    assert response.status_code == 422
    fields = {item["field"] for item in response.json()["error"]["details"]}
    assert fields == {
        "body.report_date",
        "body.planned_work",
        "body.actual_work",
        "body.next_day_plan",
    }


# Lịch sử, chi tiết báo cáo của tôi

DAY_1, DAY_2, DAY_3 = (TODAY - timedelta(days=n) for n in (2, 1, 0))


def report_url(report_id: int) -> str:
    return f"{REPORTS_URL}/{report_id}"


@pytest.fixture
async def three_reports(
    db_session: AsyncSession, department: Department, author: User
) -> list[DailyReport]:
    return [
        await create_report(db_session, author=author, department=department, report_date=day)
        for day in (DAY_1, DAY_2, DAY_3)
    ]


@pytest.mark.parametrize("path", ["", "/1"], ids=["list", "detail"])
async def test_my_reports_require_login(client: AsyncClient, path: str) -> None:
    response = await client.get(f"{REPORTS_URL}{path}")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
async def test_non_user_role_cannot_view_my_reports(
    client: AsyncClient, db_session: AsyncSession, department: Department, role: UserRole
) -> None:
    # Q3: chỉ role USER có báo cáo; kể cả báo cáo viết khi còn là USER cũng không xem qua /me.
    user = await create_user(db_session, role=role, department=department)
    report = await create_report(db_session, author=user, department=department, report_date=DAY_1)

    responses = [
        await client.get(REPORTS_URL, headers=auth_headers(user)),
        await client.get(report_url(report.id), headers=auth_headers(user)),
    ]

    assert [r.status_code for r in responses] == [403, 403]


async def test_user_lists_only_own_reports_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    author: User,
    headers: dict[str, str],
) -> None:
    old_department = await create_department(db_session)
    first = await create_report(
        db_session, author=author, department=old_department, report_date=DAY_1
    )
    third = await create_report(db_session, author=author, department=department, report_date=DAY_3)
    colleague = await create_user(db_session, department=department)
    await create_report(db_session, author=colleague, department=department, report_date=DAY_2)

    response = await client.get(REPORTS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body["data"]] == [third.id, first.id]
    assert body["meta"] == {"page": 1, "page_size": DEFAULT_PAGE_SIZE, "total": 2}
    assert body["data"][1]["department_id"] == old_department.id
    assert "recipients" not in body["data"][0]


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ((1, None), [DAY_3, DAY_2]),
        ((None, 1), [DAY_2, DAY_1]),
        ((1, 1), [DAY_2]),
        ((3, None), []),
    ],
    ids=["from-inclusive", "to-inclusive", "single-day", "no-match"],
)
@pytest.mark.usefixtures("three_reports")
async def test_list_my_reports_filters_by_date_range(
    client: AsyncClient,
    headers: dict[str, str],
    days: tuple[int | None, int | None],
    expected: list[date],
) -> None:
    # days: chỉ số trong (DAY_1, DAY_2, DAY_3) của date_from, date_to; 3 là ngày sau DAY_3.
    all_days = [DAY_1, DAY_2, DAY_3, DAY_3 + timedelta(days=1)]
    params = {
        name: all_days[index].isoformat()
        for name, index in zip(("date_from", "date_to"), days, strict=True)
        if index is not None
    }

    response = await client.get(REPORTS_URL, params=params, headers=headers)

    assert response.status_code == 200
    assert [r["report_date"] for r in response.json()["data"]] == [d.isoformat() for d in expected]
    assert response.json()["meta"]["total"] == len(expected)


@pytest.mark.usefixtures("three_reports")
async def test_list_my_reports_paginates(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get(REPORTS_URL, params={"page": 2, "page_size": 2}, headers=headers)

    assert response.status_code == 200
    assert [r["report_date"] for r in response.json()["data"]] == [DAY_1.isoformat()]
    assert response.json()["meta"] == {"page": 2, "page_size": 2, "total": 3}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"date_from": "2026-03-02", "date_to": "2026-03-01"}, "query.date_to"),
        ({"date_from": "2026-13-01"}, "query.date_from"),
        ({"date_to": "hom-nay"}, "query.date_to"),
        ({"page": 0}, "query.page"),
    ],
    ids=["to-before-from", "invalid-month", "not-a-date", "page-zero"],
)
async def test_list_my_reports_rejects_invalid_query(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(REPORTS_URL, params=params, headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


async def test_user_gets_own_report_with_department_and_recipients(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    author: User,
    headers: dict[str, str],
) -> None:
    # Collation của DB (image alpine) sắp theo byte; sắp bằng Python cũng ra cùng thứ tự sai đó:
    # "Bình, Zung, an, Ánh, Đặng Văn Bình".
    names = ["Zung", "Bình", "Đặng Văn Bình", "an", "Ánh"]
    recipients = [await create_user(db_session, role=UserRole.MANAGER, full_name=n) for n in names]
    report = await create_report(
        db_session, author=author, department=department, report_date=DAY_2, recipients=recipients
    )

    response = await client.get(report_url(report.id), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["report_date"]) == (report.id, DAY_2.isoformat())
    assert body["department"] == {
        "id": department.id,
        "code": department.code,
        "name": department.name,
    }
    assert [r["full_name"] for r in body["recipients"]] == [
        "an",
        "Ánh",
        "Bình",
        "Đặng Văn Bình",
        "Zung",
    ]
    assert body["recipients"][0] == {
        "id": recipients[3].id,
        "full_name": "an",
        "email": recipients[3].email,
        "is_deleted": False,
    }


async def test_report_hides_email_of_deleted_recipient(
    client: AsyncClient,
    db_session: AsyncSession,
    department: Department,
    author: User,
    headers: dict[str, str],
) -> None:
    # Email chỉ unique trên user chưa xóa: tài khoản mới có thể đang dùng lại email này.
    deleted = await create_user(db_session, role=UserRole.MANAGER, deleted=True)
    report = await create_report(
        db_session, author=author, department=department, report_date=DAY_1, recipients=[deleted]
    )

    response = await client.get(report_url(report.id), headers=headers)

    assert response.json()["recipients"] == [
        {"id": deleted.id, "full_name": deleted.full_name, "email": None, "is_deleted": True}
    ]


async def test_report_keeps_department_at_writing_time(
    client: AsyncClient, db_session: AsyncSession, author: User, headers: dict[str, str]
) -> None:
    # Nhân viên đã chuyển bộ phận, bộ phận cũ đã bị xóa: báo cáo cũ vẫn ghi bộ phận cũ.
    old_department = await create_department(db_session, code="OLD", deleted=True)
    report = await create_report(
        db_session, author=author, department=old_department, report_date=DAY_1
    )

    response = await client.get(report_url(report.id), headers=headers)

    assert response.status_code == 200
    assert response.json()["department"]["code"] == "OLD"
    assert response.json()["recipients"] == []


async def test_user_cannot_view_report_of_another_user(
    client: AsyncClient, db_session: AsyncSession, department: Department, headers: dict[str, str]
) -> None:
    colleague = await create_user(db_session, department=department)
    report = await create_report(
        db_session, author=colleague, department=department, report_date=DAY_1
    )

    response = await client.get(report_url(report.id), headers=headers)

    assert response.status_code == 404
    assert error_of(response.json()) == ("NOT_FOUND", {"field": "report_id"})


async def test_get_missing_report_returns_404(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get(report_url(999999), headers=headers)

    assert response.status_code == 404
    assert error_of(response.json()) == ("NOT_FOUND", {"field": "report_id"})


@pytest.mark.parametrize("report_id", [0, BIGINT_MAX + 1], ids=["zero", "over-bigint"])
async def test_report_id_out_of_range_returns_422(
    client: AsyncClient, headers: dict[str, str], report_id: int
) -> None:
    response = await client.get(report_url(report_id), headers=headers)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["path.report_id"]
