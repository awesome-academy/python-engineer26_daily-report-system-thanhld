import unicodedata
from datetime import date, datetime, time
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import messages
from app.core.constants import EXCEL_DATE_FORMAT
from app.modules.users.exceptions import ImportRowError
from app.modules.users.importing import FIELDS, UserImportRow, parse_import_file, sort_errors
from app.modules.users.models import UserRole
from tests.helpers import user_import_file

REQUIRED = {"email": "an@example.com", "full_name": "Nguyễn Văn An"}
DATE_INVALID = messages.IMPORT_DATE_INVALID.format(date_format=EXCEL_DATE_FORMAT)


def test_template_columns_match_import_row_fields() -> None:
    # Thứ tự cột của file mẫu là thứ tự đọc file: thêm field mà quên cột thì không bao giờ đọc được.
    assert tuple(UserImportRow.model_fields) == FIELDS


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (
            # Ô ngày của Excel không có múi giờ.
            {"date_of_birth": datetime(1995, 4, 30, 8, 0)},  # noqa: DTZ001
            {"date_of_birth": date(1995, 4, 30)},
        ),
        ({"date_of_birth": date(1995, 4, 30)}, {"date_of_birth": date(1995, 4, 30)}),
        ({"date_of_birth": "30/04/1995"}, {"date_of_birth": date(1995, 4, 30)}),
        ({"date_of_birth": "1/5/1995"}, {"date_of_birth": date(1995, 5, 1)}),
        ({"date_of_birth": "1995-04-30"}, {"date_of_birth": date(1995, 4, 30)}),
        ({"role": "manager"}, {"role": UserRole.MANAGER}),
        ({"department_code": 101}, {"department_code": "101"}),
        ({"department_code": "dev"}, {"department_code": "DEV"}),
    ],
    ids=[
        "datetime-cell",
        "date",
        "date-text-vn",
        "date-text-vn-short",
        "date-text-iso",
        "role-lowercase",
        "department-code-number-cell",
        "department-code-lowercase",
    ],
)
def test_import_row_reads_excel_cell_values(
    cells: dict[str, Any], expected: dict[str, Any]
) -> None:
    user = UserImportRow.model_validate(REQUIRED | cells)

    assert {field: getattr(user, field) for field in expected} == expected


@pytest.mark.parametrize(
    ("cells", "message"),
    [
        ({"phone": 901234567}, messages.IMPORT_PHONE_NOT_TEXT),
        ({"phone": 84.0}, messages.IMPORT_PHONE_NOT_TEXT),
        ({"date_of_birth": 34820}, DATE_INVALID),
        ({"date_of_birth": "30-04-1995"}, DATE_INVALID),
        ({"date_of_birth": time(8, 0)}, DATE_INVALID),
    ],
    ids=["phone-int", "phone-float", "date-number", "date-text", "date-time-cell"],
)
def test_import_row_explains_cell_type_errors(cells: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserImportRow.model_validate(REQUIRED | cells)

    [error] = exc_info.value.errors()
    assert message in error["msg"]


def test_import_row_rejects_non_ascii_role_that_uppercases_to_a_role() -> None:
    # Chữ i không chấm của tiếng Thổ: upper() thành "ADMIN", không được thành tài khoản admin.
    role = "adm\N{LATIN SMALL LETTER DOTLESS I}n"
    assert role.upper() == UserRole.ADMIN

    with pytest.raises(ValidationError):
        UserImportRow.model_validate(REQUIRED | {"role": role})


def test_sort_errors_orders_by_row_then_column() -> None:
    errors = [
        ImportRowError(3, "role", "x"),
        ImportRowError(2, "phone", "x"),
        ImportRowError(3, "email", "x"),
        ImportRowError(2, None, "x"),
    ]

    assert [(error.row, error.field) for error in sort_errors(errors)] == [
        (2, None),
        (2, "phone"),
        (3, "email"),
        (3, "role"),
    ]


def test_row_with_invalid_cell_still_checks_normalized_email_and_department_code() -> None:
    # Dòng 3 có ô số điện thoại sai: ô email (dạng Unicode NFD) và mã bộ phận (ô số) vẫn được
    # chuẩn hóa như dòng hợp lệ, nên lỗi trùng email báo ngay, không đợi admin sửa số điện thoại.
    email = "é@example.com"
    decomposed = unicodedata.normalize("NFD", email)
    assert decomposed != email

    parsed = parse_import_file(
        user_import_file([email, "Nguyễn Văn An"], [decomposed, "Trần Thị Bình", "abc", None, 101])
    )

    assert [(error.row, error.field) for error in sort_errors(parsed.errors)] == [
        (3, "email"),
        (3, "phone"),
    ]
    assert parsed.rows[1].department_code == "101"
