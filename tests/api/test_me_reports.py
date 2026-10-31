from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import (
    BIGINT_MAX,
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
    return await create_user(db_session, department=department)


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
    user = await create_user(db_session, department=department)

    response = await client.post(REPORTS_URL, json=report_body(), headers=auth_headers(user))

    assert response.status_code == 422
    assert error_of(response.json()) == ("INVALID_RECIPIENT", {"field": "recipient_ids"})
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
