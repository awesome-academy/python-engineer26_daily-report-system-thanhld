from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import IO, Any
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from httpx import AsyncClient, Response
from kombu.exceptions import OperationalError
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker
from app.core import messages
from app.core.config import get_settings
from app.core.constants import (
    EXCEL_DATE_FORMAT,
    EXCEL_TEXT_FORMAT,
    USER_IMPORT_MAX_BYTES,
    USER_IMPORT_MAX_ROWS,
    USER_IMPORT_TEMPLATE_FILENAME,
    XLSX_MAX_UNCOMPRESSED_BYTES,
    XLSX_MEDIA_TYPE,
    ZIP_SIGNATURE,
)
from app.modules.auth.tasks import send_account_setup_email
from app.modules.users import service as user_service_module
from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.importing import (
    COLUMNS,
    DATA_SHEET_TITLE,
    FIELDS,
    GUIDE_SHEET_TITLE,
    write_import_template,
)
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_user
from tests.helpers import (
    USER_IMPORT_HEADER,
    QueuedTask,
    capture_module_logs,
    queued_tasks,
    user_import_file,
    xlsx_file,
)

API = get_settings().api_v1_prefix
TEMPLATE_URL = f"{API}/admin/users/import-template"
IMPORT_URL = f"{API}/admin/users/import"


@pytest.fixture
async def admin(db_session: AsyncSession) -> User:
    return await create_user(
        db_session, email="admin@example.com", full_name="Quản trị viên", role=UserRole.ADMIN
    )


@pytest.fixture
def headers(admin: User) -> dict[str, str]:
    return auth_headers(admin)


def row(
    email: object = "an@example.com",
    full_name: object = "Nguyễn Văn An",
    *,
    phone: object = None,
    date_of_birth: object = None,
    department_code: object = None,
    role: object = None,
) -> list[object]:
    """Một dòng của file import theo đúng thứ tự cột của file mẫu."""
    return [email, full_name, phone, date_of_birth, department_code, role]


def column_letter(field: str) -> str:
    return get_column_letter(FIELDS.index(field) + 1)


async def upload(client: AsyncClient, headers: dict[str, str], data: bytes) -> Response:
    return await client.post(
        IMPORT_URL, files={"file": ("nhan-vien.xlsx", data, XLSX_MEDIA_TYPE)}, headers=headers
    )


def error_cells(response: Response) -> list[tuple[int, str | None]]:
    return [(error["row"], error["field"]) for error in response.json()["error"]["details"]]


async def count_users(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


# File mẫu


async def test_admin_downloads_import_template(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get(TEMPLATE_URL, headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{USER_IMPORT_TEMPLATE_FILENAME}"'
    )
    workbook = load_workbook(BytesIO(response.content))
    assert workbook.sheetnames == [DATA_SHEET_TITLE, GUIDE_SHEET_TITLE]
    sheet = workbook[DATA_SHEET_TITLE]
    assert isinstance(sheet, Worksheet)
    assert [cell.value for cell in sheet[1]] == USER_IMPORT_HEADER
    assert sheet.max_row == 1
    # Số điện thoại ô chữ để giữ số 0 đầu, ngày sinh ô ngày, role chọn từ danh sách.
    assert sheet.column_dimensions[column_letter("phone")].number_format == EXCEL_TEXT_FORMAT
    assert sheet.column_dimensions[column_letter("date_of_birth")].number_format == (
        EXCEL_DATE_FORMAT
    )
    [roles] = sheet.data_validations.dataValidation
    role_column = column_letter("role")
    assert (roles.formula1, str(roles.sqref)) == (
        '"USER,MANAGER,ADMIN"',
        f"{role_column}2:{role_column}{USER_IMPORT_MAX_ROWS + 1}",
    )
    guide = workbook[GUIDE_SHEET_TITLE]
    assert isinstance(guide, Worksheet)
    rules = list(guide.iter_rows(min_row=2, max_row=len(COLUMNS) + 1, values_only=True))
    assert [(header, rule) for header, _, rule in rules] == [
        (column.excel.header, column.rule) for column in COLUMNS
    ]


async def test_filled_template_imports_and_keeps_phone_leading_zero(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    template = await client.get(TEMPLATE_URL, headers=headers)
    workbook = load_workbook(BytesIO(template.content))
    sheet = workbook[DATA_SHEET_TITLE]
    assert isinstance(sheet, Worksheet)
    sheet.append(row(phone="0901234567"))
    filled = BytesIO()
    workbook.save(filled)

    response = await upload(client, headers, filled.getvalue())

    assert response.status_code == 201
    assert response.json()["users"][0]["phone"] == "0901234567"


async def test_template_releases_db_connection_before_writing_file(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bước xác thực đọc DB bằng session của request, mà session chỉ đóng sau khi gửi xong file
    # (StreamingResponse): còn transaction thì kết nối bị giữ suốt lúc ghi file và lúc client tải.
    in_transaction: list[bool] = []

    def write() -> IO[bytes]:
        in_transaction.append(db_session.in_transaction())
        return write_import_template()

    monkeypatch.setattr(user_service_module, "write_import_template", write)

    response = await client.get(TEMPLATE_URL, headers=headers)

    assert response.status_code == 200
    assert in_transaction == [False]


@pytest.mark.parametrize(
    ("method", "url"), [("GET", TEMPLATE_URL), ("POST", IMPORT_URL)], ids=["template", "import"]
)
async def test_import_endpoints_require_admin(
    client: AsyncClient, db_session: AsyncSession, method: str, url: str
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)

    no_token = await client.request(method, url)
    wrong_role = await client.request(method, url, headers=auth_headers(manager))

    assert (no_token.status_code, wrong_role.status_code) == (401, 403)


# Import thành công


async def test_admin_imports_users_and_queues_setup_emails(
    client: AsyncClient, db_session: AsyncSession, redis: Redis, headers: dict[str, str]
) -> None:
    department = await create_department(db_session, code="DEV")
    data = user_import_file(
        row(
            "an@example.com",
            phone="0901234567",
            date_of_birth=date(1995, 4, 30),
            department_code="DEV",
            role="MANAGER",
        ),
        row("binh@example.com", "Trần Thị Bình"),
    )

    response = await upload(client, headers, data)

    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2
    an, binh = body["users"]
    assert {key: an[key] for key in ("email", "phone", "date_of_birth", "role")} == {
        "email": "an@example.com",
        "phone": "0901234567",
        "date_of_birth": "1995-04-30",
        "role": "MANAGER",
    }
    assert (an["department_id"], an["is_active"]) == (department.id, True)
    assert (binh["role"], binh["department_id"], binh["phone"]) == ("USER", None, None)
    created = await db_session.scalars(select(User).where(User.id.in_([an["id"], binh["id"]])))
    # Chưa có mật khẩu: user tự đặt qua link trong email (S2) như tạo từng người.
    assert [user.password_hash for user in created] == [None, None]
    assert await queued_tasks(redis) == [
        QueuedTask(name=send_account_setup_email.name, args=[an["id"]], kwargs={}),
        QueuedTask(name=send_account_setup_email.name, args=[binh["id"]], kwargs={}),
    ]


async def test_import_matches_department_code_ignoring_case_and_number_cells(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    dev = await create_department(db_session, code="DEV")
    # Excel lưu mã "101" gõ vào ô thường thành số.
    numeric = await create_department(db_session, code="101")
    data = user_import_file(
        row("an@example.com", department_code=" dev "),
        row("binh@example.com", department_code=101),
    )

    response = await upload(client, headers, data)

    assert response.status_code == 201
    assert [user["department_id"] for user in response.json()["users"]] == [dev.id, numeric.id]


async def test_import_skips_blank_rows_and_reports_excel_row_numbers(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    data = user_import_file(row("an@example.com"), [], ["   ", None], row("khong-phai-email"))

    response = await upload(client, headers, data)

    assert response.status_code == 422
    assert error_cells(response) == [(5, "email")]


async def test_import_reuses_email_of_deleted_user(
    client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await create_user(db_session, email="an@example.com", deleted=True)

    response = await upload(client, headers, user_import_file(row("an@example.com")))

    assert response.status_code == 201


async def test_import_accepts_header_ignoring_case_and_extra_columns(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    header = [title.upper() for title in USER_IMPORT_HEADER] + ["Ghi chú"]

    response = await upload(client, headers, xlsx_file([header, [*row(), "không đọc cột này"]]))

    assert response.status_code == 201


async def test_import_accepts_max_rows(
    client: AsyncClient, redis: Redis, headers: dict[str, str]
) -> None:
    rows = [row(f"user{index}@example.com") for index in range(USER_IMPORT_MAX_ROWS)]

    response = await upload(client, headers, user_import_file(*rows))

    assert response.status_code == 201
    assert response.json()["created_count"] == USER_IMPORT_MAX_ROWS
    assert len(await queued_tasks(redis)) == USER_IMPORT_MAX_ROWS


async def test_import_stops_queueing_emails_when_queue_is_down(
    client: AsyncClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []

    def broker_down(*args: Any) -> None:
        calls.append(args)
        raise OperationalError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(send_account_setup_email, "delay", broker_down)
    worker_logs = capture_module_logs(monkeypatch, worker)
    service_logs = capture_module_logs(monkeypatch, user_service_module)

    response = await upload(
        client, headers, user_import_file(row("an@example.com"), row("binh@example.com"))
    )

    # Tài khoản đã lưu: vẫn trả 201 như tạo từng người.
    assert response.status_code == 201
    ids = [user["id"] for user in response.json()["users"]]
    # Dừng ở lần lỗi đầu: Redis lỗi thì lần nào cũng chờ timeout, 1.000 lần là treo request.
    assert calls == [(ids[0],)]
    assert [log["event"] for log in worker_logs] == ["task_enqueue_failed"]
    [pending] = [log for log in service_logs if log["event"] == "account_setup_emails_not_queued"]
    assert pending["user_ids"] == ids


# Lỗi theo dòng


@pytest.mark.parametrize(
    ("cells", "field"),
    [
        ({"email": "khong-phai-email"}, "email"),
        ({"email": None}, "email"),
        ({"full_name": "   "}, "full_name"),
        ({"phone": 901234567}, "phone"),
        ({"phone": "12ab"}, "phone"),
        ({"date_of_birth": 34820}, "date_of_birth"),
        ({"date_of_birth": "30-04-1995"}, "date_of_birth"),
        ({"date_of_birth": datetime.now(UTC).date() + timedelta(days=2)}, "date_of_birth"),
        ({"department_code": "phòng"}, "department_code"),
        ({"role": "BOSS"}, "role"),
    ],
    ids=[
        "email",
        "email-missing",
        "full-name-blank",
        "phone-number-cell",
        "phone",
        "date-number-cell",
        "date-text",
        "date-future",
        "department-code",
        "role",
    ],
)
async def test_import_rejects_invalid_cell(
    client: AsyncClient,
    headers: dict[str, str],
    cells: dict[str, object],
    field: str,
) -> None:
    response = await upload(client, headers, user_import_file(row(**cells)))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_VALIDATION_FAILED"
    assert error_cells(response) == [(2, field)]


async def test_import_with_errors_creates_nobody_and_reports_every_error(
    client: AsyncClient, db_session: AsyncSession, redis: Redis, headers: dict[str, str]
) -> None:
    await create_department(db_session, code="DEV")
    await create_department(db_session, code="OLD", deleted=True)
    await create_user(db_session, email="taken@example.com")
    # Commit dữ liệu chuẩn bị: có lỗi thì service rollback (nhả khóa bộ phận), chỉ bỏ phần service
    # đã ghi.
    await db_session.commit()
    users_before = await count_users(db_session)
    data = user_import_file(
        row("an@example.com", department_code="DEV"),
        # Ô số điện thoại sai nhưng ô email hợp lệ: vẫn xét email đã có tài khoản.
        row("Taken@Example.com", phone="12ab"),
        row("binh@example.com", department_code="OLD"),
        row("AN@example.com", role="BOSS"),
    )

    response = await upload(client, headers, data)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["message"] == messages.IMPORT_FAILED.format(count=5)
    # Theo dòng, rồi theo thứ tự cột trên file.
    assert error_cells(response) == [
        (3, "email"),
        (3, "phone"),
        (4, "department_code"),
        (5, "email"),
        (5, "role"),
    ]
    by_cell = {(item["row"], item["field"]): item["message"] for item in error["details"]}
    assert by_cell[3, "email"] == EmailAlreadyExistsError.message
    assert by_cell[4, "department_code"] == messages.IMPORT_DEPARTMENT_NOT_FOUND
    assert by_cell[5, "email"] == messages.IMPORT_EMAIL_DUPLICATED.format(row=2)
    assert await count_users(db_session) == users_before
    assert await queued_tasks(redis) == []


@pytest.mark.parametrize(
    ("rows", "fields"),
    [
        pytest.param([], list(FIELDS), id="empty-sheet"),
        pytest.param(
            [["Email", "Số điện thoại", "Họ tên", "Ngày sinh", "Mã bộ phận", "Role"], row()],
            ["full_name", "phone"],
            id="swapped-columns",
        ),
    ],
)
async def test_import_rejects_header_unlike_template(
    client: AsyncClient, headers: dict[str, str], rows: list[list[object]], fields: list[str]
) -> None:
    response = await upload(client, headers, xlsx_file(rows))

    assert response.status_code == 422
    assert error_cells(response) == [(1, field) for field in fields]


async def test_import_rejects_file_without_data_rows(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await upload(client, headers, user_import_file([], []))

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"row": 2, "field": None, "message": messages.IMPORT_NO_DATA_ROWS}
    ]


async def test_import_rejects_more_than_max_rows(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    rows = [row(f"user{index}@example.com") for index in range(USER_IMPORT_MAX_ROWS + 1)]

    response = await upload(client, headers, user_import_file(*rows))

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {
            "row": USER_IMPORT_MAX_ROWS + 2,
            "field": None,
            "message": messages.IMPORT_TOO_MANY_ROWS.format(max_rows=USER_IMPORT_MAX_ROWS),
        }
    ]


# Lỗi file


async def test_import_rejects_file_over_size_limit(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await upload(client, headers, ZIP_SIGNATURE + b"0" * USER_IMPORT_MAX_BYTES)

    assert response.status_code == 413
    assert response.json()["error"]["details"] == {
        "field": "file",
        "max_bytes": USER_IMPORT_MAX_BYTES,
    }


async def test_import_rejects_zip_bomb(client: AsyncClient, headers: dict[str, str]) -> None:
    bomb = BytesIO()
    with ZipFile(bomb, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", b"0" * (XLSX_MAX_UNCOMPRESSED_BYTES + 1))
    # Nén lại chỉ vài KB, dưới giới hạn tải lên.
    assert len(bomb.getvalue()) < USER_IMPORT_MAX_BYTES

    response = await upload(client, headers, bomb.getvalue())

    assert response.status_code == 413
    assert response.json()["error"]["details"] == {
        "field": "file",
        "max_uncompressed_bytes": XLSX_MAX_UNCOMPRESSED_BYTES,
    }


@pytest.mark.parametrize(
    "data",
    [b"email,ho_ten\nan@example.com,An\n", user_import_file(row())[:-100]],
    ids=["csv", "truncated-xlsx"],
)
async def test_import_rejects_non_xlsx_file(
    client: AsyncClient, headers: dict[str, str], data: bytes
) -> None:
    response = await upload(client, headers, data)

    assert response.status_code == 415
    assert response.json()["error"]["details"] == {
        "field": "file",
        "allowed_types": [XLSX_MEDIA_TYPE],
    }


async def test_import_requires_file_field(client: AsyncClient, headers: dict[str, str]) -> None:
    response = await client.post(IMPORT_URL, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.file"


async def test_swagger_documents_import_endpoints(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert XLSX_MEDIA_TYPE in paths[TEMPLATE_URL]["get"]["responses"]["200"]["content"]
    assert {"201", "401", "403", "409", "413", "415", "422"} <= set(
        paths[IMPORT_URL]["post"]["responses"]
    )
