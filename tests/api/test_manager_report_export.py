"""Manager export Excel báo cáo một ngày của bộ phận mình quản lý (M5).

Bộ lọc `department_id` ngoài phạm vi (bộ phận khác, đã xóa, role sai, id sai) chạy theo ma trận
quyền ở tests/api/test_department_scope.py; ở đây là nội dung file.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import IO, Any, Self
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from openpyxl.cell.cell import Cell, MergedCell
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import EXCEL_DATETIME_FORMAT, XLSX_MEDIA_TYPE
from app.core.exceptions import AppError, ForbiddenError, UnauthorizedError
from app.modules.departments.models import Department
from app.modules.reports import service as report_service
from app.modules.reports.export import (
    COLUMNS,
    MISSING_FILL,
    SubmissionStatus,
    write_report_workbook,
)
from app.modules.reports.models import DailyReport
from app.modules.reports.schemas import ReportExportRow
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_report, create_user
from tests.helpers import error_json, load_sheet

API = get_settings().api_v1_prefix
EXPORT_URL = f"{API}/manager/reports/export"
TIMEZONE = ZoneInfo(get_settings().timezone)
DAY = date(2026, 3, 2)
TODAY = date(2026, 3, 4)
JOINED = datetime(2026, 1, 5, tzinfo=UTC)
SUBMITTED = SubmissionStatus.SUBMITTED
MISSING = SubmissionStatus.MISSING
# Cột trong file: mã bộ phận, bộ phận, nhân viên, email, trạng thái, 4 nội dung, giờ gửi.
STATUS_COLUMN = 4
CONTENT_COLUMNS = slice(5, 9)
SUBMITTED_AT_COLUMN = 9


def sheet_rows(response: Response) -> list[tuple[Any, ...]]:
    """Giá trị các dòng dưới tiêu đề của file trả về (đã kiểm tra tiêu đề)."""
    rows = list(load_sheet(response).iter_rows(values_only=True))
    assert rows[0] == tuple(column.header for column in COLUMNS)
    return rows[1:]


def sheet_cells(response: Response) -> list[tuple[Cell | MergedCell, ...]]:
    return list(load_sheet(response).iter_rows(min_row=2))


def summary(rows: list[tuple[Any, ...]]) -> list[tuple[str, str, SubmissionStatus]]:
    """Mã bộ phận, họ tên, trạng thái của từng dòng."""
    return [(row[0], row[2], SubmissionStatus(row[STATUS_COLUMN])) for row in rows]


@pytest.fixture(autouse=True)
def fixed_today(app: FastAPI) -> None:
    app.dependency_overrides[local_today] = lambda: TODAY


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, full_name="Quản Lý", role=UserRole.MANAGER)


@pytest.fixture
def headers(manager: User) -> dict[str, str]:
    return auth_headers(manager)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, code="KT", name="Kỹ thuật", managers=[manager])


async def employee(session: AsyncSession, department: Department, **fields: Any) -> User:
    """Nhân viên đã có tài khoản từ trước DAY: user tạo trong test mang giờ thật, sau DAY."""
    return await create_user(session, department=department, created_at=JOINED, **fields)


async def submit(
    session: AsyncSession, author: User, department: Department, report_date: date = DAY
) -> DailyReport:
    return await create_report(
        session, author=author, department=department, report_date=report_date
    )


async def export(
    client: AsyncClient, headers: dict[str, str], **params: Any
) -> list[tuple[Any, ...]]:
    response = await client.get(
        EXPORT_URL, params={"date": DAY.isoformat(), **params}, headers=headers
    )
    assert response.status_code == 200
    return sheet_rows(response)


# Nội dung file


async def test_manager_exports_day_with_missing_employees_marked(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    qa = await create_department(db_session, code="QA", name="Kiểm thử", managers=[manager])
    binh = await employee(db_session, department, full_name="Trần Bình")
    await employee(db_session, department, full_name="Đặng Cường")
    an = await employee(db_session, qa, full_name="Lê An")
    report = await submit(db_session, binh, department)
    # 01:30 UTC là 08:30 giờ Việt Nam.
    report.created_at = datetime(2026, 3, 2, 1, 30, tzinfo=UTC)
    report.incomplete_reason = "Chờ review"
    await submit(db_session, an, qa)
    await db_session.flush()

    response = await client.get(EXPORT_URL, params={"date": DAY.isoformat()}, headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert (
        response.headers["content-disposition"] == 'attachment; filename="bao-cao-2026-03-02.xlsx"'
    )
    assert response.headers["content-length"] == str(len(response.content))
    rows = sheet_rows(response)
    # Sắp theo mã bộ phận rồi họ tên không dấu: "Đặng" trước "Trần".
    assert summary(rows) == [
        ("KT", "Đặng Cường", MISSING),
        ("KT", "Trần Bình", SUBMITTED),
        ("QA", "Lê An", SUBMITTED),
    ]
    assert rows[1] == (
        "KT",
        "Kỹ thuật",
        "Trần Bình",
        binh.email,
        SUBMITTED,
        report.planned_work,
        report.actual_work,
        "Chờ review",
        report.next_day_plan,
        # Excel không lưu múi giờ: giờ Việt Nam.
        datetime(2026, 3, 2, 8, 30, tzinfo=TIMEZONE).replace(tzinfo=None),
    )
    # Chưa nộp: không có nội dung, giờ gửi.
    assert rows[0][CONTENT_COLUMNS] == (None, None, None, None)
    assert rows[0][SUBMITTED_AT_COLUMN] is None
    cells = sheet_cells(response)
    assert cells[0][STATUS_COLUMN].fill.fgColor.rgb.endswith(MISSING_FILL.fgColor.rgb)
    assert cells[1][STATUS_COLUMN].fill.fill_type is None
    assert cells[1][SUBMITTED_AT_COLUMN].number_format == EXCEL_DATETIME_FORMAT


async def test_export_only_covers_managed_departments_and_the_day(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    author = await employee(db_session, department, full_name="Trần Bình")
    await submit(db_session, author, department, report_date=DAY - timedelta(days=1))
    # Ngoài phạm vi: bộ phận người khác quản lý, bộ phận manager chỉ là thành viên, bộ phận đã xóa.
    other = await create_department(db_session)
    member_only = await create_department(db_session)
    manager.department_id = member_only.id
    deleted = await create_department(db_session, managers=[manager], deleted=True)
    for outside in (other, member_only, deleted):
        await submit(db_session, await employee(db_session, outside), outside)
        await employee(db_session, outside)

    rows = await export(client, headers)

    # Báo cáo ngày khác không tính: hôm đó Bình chưa nộp.
    assert summary(rows) == [("KT", "Trần Bình", MISSING)]


async def test_manager_without_departments_gets_header_only(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    other = await create_department(db_session)
    await submit(db_session, await employee(db_session, other), other)

    assert await export(client, headers) == []


async def test_manager_exports_one_managed_department(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    qa = await create_department(db_session, code="QA", managers=[manager])
    await employee(db_session, department, full_name="Trần Bình")
    await submit(db_session, await employee(db_session, qa, full_name="Lê An"), qa)

    response = await client.get(
        EXPORT_URL, params={"date": DAY.isoformat(), "department_id": qa.id}, headers=headers
    )

    assert response.status_code == 200
    assert summary(sheet_rows(response)) == [("QA", "Lê An", SUBMITTED)]


async def test_report_stays_with_department_at_writing_time(
    client: AsyncClient,
    db_session: AsyncSession,
    manager: User,
    headers: dict[str, str],
    department: Department,
) -> None:
    qa = await create_department(db_session, code="QA", managers=[manager])
    moved = await employee(db_session, department, full_name="Trần Bình")
    await submit(db_session, moved, department)
    moved.department_id = qa.id
    await db_session.flush()

    rows = await export(client, headers)

    # Đã nộp ở bộ phận cũ thì không bị tính chưa nộp ở bộ phận mới.
    assert summary(rows) == [("KT", "Trần Bình", SUBMITTED)]


async def test_report_written_outside_scope_is_not_counted_as_missing(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    other = await create_department(db_session)
    moved = await employee(db_session, other)
    await submit(db_session, moved, other)
    moved.department_id = department.id
    await db_session.flush()

    assert await export(client, headers) == []


async def test_missing_list_counts_current_employees_only(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    await employee(db_session, department, full_name="An Khóa", is_active=False)
    await employee(db_session, department, full_name="Bình Mới", password=None)
    # Không phải nhân viên: manager, admin được xếp vào bộ phận, user đã xóa.
    for role in (UserRole.MANAGER, UserRole.ADMIN):
        await employee(db_session, department, role=role)
    await employee(db_session, department, deleted=True)

    rows = await export(client, headers)

    # Tài khoản bị khóa, chưa đặt mật khẩu vẫn là nhân viên (như M4), vẫn tính chưa nộp.
    assert summary(rows) == [("KT", "An Khóa", MISSING), ("KT", "Bình Mới", MISSING)]


async def test_employee_created_by_end_of_day_is_missing(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    end_of_day = datetime(2026, 3, 2, 23, 59, 59, tzinfo=TIMEZONE)
    await create_user(db_session, full_name="Lê Mới", department=department, created_at=end_of_day)

    assert summary(await export(client, headers)) == [("KT", "Lê Mới", MISSING)]


async def test_employee_created_after_the_day_is_not_missing(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    # Ngày theo giờ Việt Nam: 00:00 ngày 3/3 giờ Việt Nam vẫn là ngày 2/3 theo UTC.
    next_day = datetime(2026, 3, 3, 0, 0, tzinfo=TIMEZONE)
    await create_user(db_session, full_name="Lê Mới", department=department, created_at=next_day)

    assert await export(client, headers) == []


async def test_export_includes_reports_of_locked_and_deleted_authors(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    locked = await employee(db_session, department, full_name="An Khóa", is_active=False)
    deleted = await employee(db_session, department, full_name="Bình Xóa")
    await submit(db_session, locked, department)
    await submit(db_session, deleted, department)
    deleted.deleted_at = datetime.now(UTC)
    await db_session.flush()

    rows = await export(client, headers)

    assert summary(rows) == [("KT", "An Khóa", SUBMITTED), ("KT", "Bình Xóa", SUBMITTED)]
    # Email chỉ unique trên user chưa xóa, có thể đã thuộc tài khoản mới: không ghi, như M3.
    assert [row[3] for row in rows] == [locked.email, None]


async def test_user_text_is_written_as_plain_text(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    author = await employee(db_session, department, full_name="=Bình\x07\uffff")
    report = await submit(db_session, author, department)
    report.planned_work = '=HYPERLINK("http://evil.example","Bấm vào")'
    report.actual_work = "#N/A"
    report.next_day_plan = "Dòng 1\n\tDòng 2\x1b\ufffe"
    await db_session.flush()

    response = await client.get(EXPORT_URL, params={"date": DAY.isoformat()}, headers=headers)

    assert response.status_code == 200
    cells = sheet_cells(response)[0]
    # Công thức, mã lỗi trong nội dung vẫn là chữ; ký tự XML không chứa được (điều khiển trừ tab,
    # xuống dòng; U+FFFE, U+FFFF) bị bỏ, file vẫn mở được.
    assert [(cell.value, cell.data_type) for cell in (cells[2], cells[5], cells[6], cells[8])] == [
        ("=Bình", "s"),
        ('=HYPERLINK("http://evil.example","Bấm vào")', "s"),
        ("#N/A", "s"),
        ("Dòng 1\n\tDòng 2", "s"),
    ]


async def test_export_releases_db_connection_before_writing_file(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    department: Department,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Session của request chỉ đóng sau khi gửi xong file (StreamingResponse): còn transaction thì
    # kết nối DB bị giữ suốt lúc ghi file và lúc client tải.
    await employee(db_session, department)
    in_transaction: list[bool] = []

    def write(report_date: date, rows: list[ReportExportRow]) -> IO[bytes]:
        in_transaction.append(db_session.in_transaction())
        return write_report_workbook(report_date, rows)

    monkeypatch.setattr(report_service, "write_report_workbook", write)

    rows = await export(client, headers)

    assert len(rows) == 1
    assert in_transaction == [False]


# Ngày


async def test_export_defaults_to_today(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], department: Department
) -> None:
    author = await employee(db_session, department, full_name="Trần Bình")
    await submit(db_session, author, department, report_date=TODAY)

    response = await client.get(EXPORT_URL, headers=headers)

    assert response.status_code == 200
    assert (
        response.headers["content-disposition"] == 'attachment; filename="bao-cao-2026-03-04.xlsx"'
    )
    assert summary(sheet_rows(response)) == [("KT", "Trần Bình", SUBMITTED)]


class LateEveningUtc(datetime):
    """Đồng hồ dừng ở 17:30 UTC ngày 4/3, đã là 00:30 ngày 5/3 giờ Việt Nam."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 3, 4, 17, 30, tzinfo=UTC).astimezone(tz)


async def test_export_uses_business_timezone_today(
    app: FastAPI, client: AsyncClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bỏ ngày cố định, lấy hôm nay từ local_today() với đồng hồ lúc hai múi giờ khác ngày: tính
    # theo UTC thì ra ngày 4/3.
    del app.dependency_overrides[local_today]
    monkeypatch.setattr(clock, "datetime", LateEveningUtc)

    response = await client.get(EXPORT_URL, headers=headers)

    assert response.status_code == 200
    assert (
        response.headers["content-disposition"] == 'attachment; filename="bao-cao-2026-03-05.xlsx"'
    )


async def test_export_rejects_future_date(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    # Lỗi tham số có trước lỗi phạm vi: bộ phận ngoài phạm vi vẫn nhận 422.
    other = await create_department(db_session)

    response = await client.get(
        EXPORT_URL,
        params={"date": (TODAY + timedelta(days=1)).isoformat(), "department_id": other.id},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPORT_DATE_OUT_OF_RANGE"
    assert response.json()["error"]["details"] == {"field": "date", "max_date": TODAY.isoformat()}


@pytest.mark.parametrize("value", ["2026-02-30", "02/03/2026", "abc"])
async def test_export_rejects_invalid_date_before_department_scope(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str], value: str
) -> None:
    other = await create_department(db_session)

    response = await client.get(
        EXPORT_URL, params={"date": value, "department_id": other.id}, headers=headers
    )

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["query.date"]


# Phân quyền, Swagger


@pytest.mark.parametrize(
    ("role", "error"),
    [
        (None, UnauthorizedError()),
        (UserRole.USER, ForbiddenError()),
        (UserRole.ADMIN, ForbiddenError()),
    ],
    ids=["anonymous", "user", "admin"],
)
async def test_export_requires_manager_role(
    client: AsyncClient, db_session: AsyncSession, role: UserRole | None, error: AppError
) -> None:
    caller = await create_user(db_session, role=role) if role else None
    await create_department(db_session, managers=[caller] if caller else [])

    response = await client.get(EXPORT_URL, headers=auth_headers(caller) if caller else {})

    assert response.status_code == error.status_code
    assert response.json() == error_json(error)


async def test_export_documents_file_and_errors_in_swagger(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    responses = response.json()["paths"][EXPORT_URL]["get"]["responses"]
    assert list(responses["200"]["content"]) == [XLSX_MEDIA_TYPE]
    for status_code in ("401", "403", "404", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
