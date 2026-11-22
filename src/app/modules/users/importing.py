"""File Excel import nhân viên (A4): file mẫu, đọc và kiểm tra file admin tải lên.

Ở đây là phần không cần DB: định dạng file, quy tắc từng ô (như `POST /admin/users`), email trùng
trong file. Email đã có tài khoản, mã bộ phận có thật do `UserImportService` kiểm tra.
"""

from collections.abc import Iterable, Sequence
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import IO, Any, NamedTuple

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, ConfigDict, PastDate, TypeAdapter, ValidationError, field_validator

from app.core import messages
from app.core.constants import (
    EXCEL_DATE_FORMAT,
    EXCEL_TEXT_FORMAT,
    FULL_NAME_MAX_LENGTH,
    FULL_NAME_MIN_LENGTH,
    PHONE_MAX_DIGITS,
    PHONE_MIN_DIGITS,
    USER_IMPORT_DATE_FORMATS,
    USER_IMPORT_MAX_MB,
    USER_IMPORT_MAX_ROWS,
)
from app.core.excel import ExcelColumn, iter_xlsx_rows, save_workbook, write_header
from app.modules.departments.schemas import DepartmentCode
from app.modules.users.exceptions import ImportRowError, ImportValidationError
from app.modules.users.models import UserRole
from app.modules.users.schemas import Email, FullName, Phone


class UserImportRow(BaseModel):
    """Một dòng dữ liệu: cùng quy tắc với `AdminUserCreate`, bộ phận ghi bằng mã thay cho id.

    Ô số ở cột chữ được đổi thành chữ (Excel lưu mã bộ phận "101" thành số), trừ số điện thoại.
    """

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    email: Email
    full_name: FullName
    phone: Phone | None = None
    date_of_birth: PastDate | None = None
    department_code: DepartmentCode | None = None
    role: UserRole = UserRole.USER

    @field_validator("phone", mode="before")
    @classmethod
    def _reject_number_cell(cls, value: object) -> object:
        # Ô số đã mất số 0 đầu (0901234567 thành 901234567): đổi lại thành chữ là sai số.
        if isinstance(value, int | float):
            raise ValueError(messages.IMPORT_PHONE_NOT_TEXT)
        return value

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _date_from_cell(cls, value: object) -> object:
        # Ô ngày: openpyxl trả datetime. Ô số chưa định dạng ngày thì không đoán (số ngày kiểu Excel
        # hay gõ nhầm), báo lỗi như chữ sai định dạng.
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            for date_format in USER_IMPORT_DATE_FORMATS:
                with suppress(ValueError):
                    return datetime.strptime(value, date_format).date()  # noqa: DTZ007 (chỉ lấy ngày)
        raise ValueError(messages.IMPORT_DATE_INVALID.format(date_format=EXCEL_DATE_FORMAT))

    @field_validator("role", mode="before")
    @classmethod
    def _role_ignoring_case(cls, value: object) -> object:
        # Chỉ đổi chuỗi ASCII: upper() đổi được vài ký tự không phải ASCII thành chữ ASCII (i
        # không chấm của tiếng Thổ thành I), chuỗi gõ sai sẽ thành role ADMIN.
        if isinstance(value, str) and value.isascii():
            return value.upper()
        return value


# Ô email, mã bộ phận kiểm tra riêng bằng đúng kiểu và cấu hình của UserImportRow: dòng có ô khác
# sai vẫn lấy được giá trị đã chuẩn hóa (email NFC, mã chữ hoa) để xét trùng, xét mã bộ phận.
_EMAIL_CELL = TypeAdapter(Email)
_DEPARTMENT_CODE_CELL = TypeAdapter(DepartmentCode, config=ConfigDict(coerce_numbers_to_str=True))


class ImportColumn(NamedTuple):
    field: str
    excel: ExcelColumn
    required: bool
    # Quy tắc ghi trong sheet hướng dẫn của file mẫu.
    rule: str


# Thứ tự cột của file mẫu, file tải lên phải giữ đúng thứ tự này (Q10).
COLUMNS = (
    ImportColumn(
        "email",
        ExcelColumn("Email", 30),
        required=True,
        rule="Không trùng email của tài khoản khác hay dòng khác trong file (không phân biệt hoa "
        "thường).",
    ),
    ImportColumn(
        "full_name",
        ExcelColumn("Họ tên", 28),
        required=True,
        rule=f"Từ {FULL_NAME_MIN_LENGTH} đến {FULL_NAME_MAX_LENGTH} ký tự.",
    ),
    ImportColumn(
        "phone",
        ExcelColumn("Số điện thoại", 18, EXCEL_TEXT_FORMAT),
        required=False,
        rule=f"Chỉ chữ số, có thể có dấu + ở đầu, {PHONE_MIN_DIGITS} đến {PHONE_MAX_DIGITS} chữ "
        "số. Nhập ở ô định dạng chữ (Text) để giữ số 0 đầu.",
    ),
    ImportColumn(
        "date_of_birth",
        ExcelColumn("Ngày sinh", 14, EXCEL_DATE_FORMAT),
        required=False,
        rule=f"Ngày trong quá khứ: ô kiểu ngày, hoặc chữ dạng {EXCEL_DATE_FORMAT}.",
    ),
    ImportColumn(
        "department_code",
        ExcelColumn("Mã bộ phận", 16),
        required=False,
        rule="Mã của bộ phận đang có (không phân biệt hoa thường). Bỏ trống: chưa xếp bộ phận.",
    ),
    ImportColumn(
        "role",
        ExcelColumn("Role", 12),
        required=False,
        rule=f"{', '.join(UserRole)}. Bỏ trống là {UserRole.USER}.",
    ),
)
FIELDS = tuple(column.field for column in COLUMNS)
_COLUMN_POSITIONS = {field: position for position, field in enumerate(FIELDS)}
HEADER_ROW = 1
FIRST_DATA_ROW = HEADER_ROW + 1
LAST_DATA_ROW = HEADER_ROW + USER_IMPORT_MAX_ROWS

DATA_SHEET_TITLE = "Nhân viên"
GUIDE_SHEET_TITLE = "Hướng dẫn"
GUIDE_COLUMNS = (ExcelColumn("Cột", 16), ExcelColumn("Bắt buộc", 10), ExcelColumn("Quy tắc", 90))
REQUIRED_LABELS = {True: "Có", False: "Không"}
GUIDE_NOTES = (
    f'Điền từ dòng {FIRST_DATA_ROW} của sheet "{DATA_SHEET_TITLE}", giữ nguyên dòng tiêu đề. '
    f"Tối đa {USER_IMPORT_MAX_ROWS} dòng, file tối đa {USER_IMPORT_MAX_MB} MB.",
    "Có lỗi ở bất kỳ dòng nào thì không tạo tài khoản nào; kết quả liệt kê lỗi theo dòng để sửa.",
    "Tài khoản mới chưa có mật khẩu: mỗi người nhận email có link để tự đặt mật khẩu.",
)


@dataclass(frozen=True, slots=True)
class ImportRow:
    """Một dòng có dữ liệu. `user` là None khi dòng có ô sai.

    `email` (chữ thường) và `department_code` (chữ hoa như mã đã lưu) có giá trị khi riêng ô đó
    hợp lệ, kể cả khi ô khác của dòng sai: xét trùng email, xét mã bộ phận ngay trong lần này để
    admin sửa mọi lỗi một lần.
    """

    row: int
    user: UserImportRow | None
    email: str | None
    department_code: str | None


@dataclass(frozen=True, slots=True)
class ParsedImport:
    rows: list[ImportRow]
    errors: list[ImportRowError]


def write_import_template() -> IO[bytes]:
    """File mẫu: sheet nhập liệu (dòng tiêu đề, định dạng cột, chọn role) và sheet hướng dẫn.

    Hàm chặn (openpyxl đồng bộ): gọi trong `asyncio.to_thread`.
    """
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(DATA_SHEET_TITLE)
    write_header(sheet, [column.excel for column in COLUMNS])
    role_column = get_column_letter(_COLUMN_POSITIONS["role"] + 1)
    roles = DataValidation(type="list", formula1=f'"{",".join(UserRole)}"', allow_blank=True)
    roles.add(f"{role_column}{FIRST_DATA_ROW}:{role_column}{LAST_DATA_ROW}")
    sheet.data_validations.append(roles)

    guide = workbook.create_sheet(GUIDE_SHEET_TITLE)
    write_header(guide, GUIDE_COLUMNS)
    for column in COLUMNS:
        guide.append([column.excel.header, REQUIRED_LABELS[column.required], column.rule])
    guide.append([])
    for note in GUIDE_NOTES:
        guide.append([note])
    return save_workbook(workbook)


def parse_import_file(data: bytes) -> ParsedImport:
    """Đọc sheet đầu tiên của file import, kiểm tra từng dòng.

    Không phải .xlsx: 415; giải nén quá lớn: 413. Tiêu đề sai, không có dòng dữ liệu, quá
    `USER_IMPORT_MAX_ROWS` dòng: ném ImportValidationError ngay, không xét tiếp. Lỗi của từng dòng
    gom vào `errors` để báo cùng lỗi phải tra DB. Dòng trống bỏ qua. Hàm chặn: gọi trong
    `asyncio.to_thread`.
    """
    rows: list[ImportRow] = []
    errors: list[ImportRowError] = []
    with closing(iter_xlsx_rows(data, len(COLUMNS))) as lines:
        _check_header(next(lines, ()))
        for row_number, values in enumerate(lines, start=FIRST_DATA_ROW):
            cleaned = (_clean(value) for value in values)
            cells = {
                field: value
                for field, value in zip(FIELDS, cleaned, strict=False)
                if value is not None
            }
            if not cells:
                continue
            if len(rows) == USER_IMPORT_MAX_ROWS:
                message = messages.IMPORT_TOO_MANY_ROWS.format(max_rows=USER_IMPORT_MAX_ROWS)
                raise ImportValidationError([ImportRowError(row_number, None, message)])
            row, row_errors = _parse_row(row_number, cells)
            rows.append(row)
            errors.extend(row_errors)
    if not rows:
        raise ImportValidationError(
            [ImportRowError(FIRST_DATA_ROW, None, messages.IMPORT_NO_DATA_ROWS)]
        )
    errors.extend(_duplicate_email_errors(rows))
    return ParsedImport(rows, errors)


def sort_errors(errors: Iterable[ImportRowError]) -> list[ImportRowError]:
    """Theo dòng, rồi theo cột như trên file: admin sửa lần lượt từ trên xuống."""
    return sorted(
        errors,
        key=lambda error: (
            error.row,
            -1 if error.field is None else _COLUMN_POSITIONS[error.field],
        ),
    )


def _clean(value: object) -> object:
    # Ô chữ bỏ khoảng trắng đầu cuối; chỉ có khoảng trắng là ô trống.
    if isinstance(value, str):
        return value.strip() or None
    return value


def _check_header(values: Sequence[Any]) -> None:
    """Dòng 1 phải đúng tiêu đề của file mẫu (không phân biệt hoa thường).

    Sai thì dừng, không xét các dòng: cột lệch thì ô nào cũng bị đọc nhầm sang cột khác.
    """
    errors = [
        ImportRowError(
            HEADER_ROW,
            column.field,
            messages.IMPORT_HEADER_MISMATCH.format(
                column=get_column_letter(position + 1), header=column.excel.header
            ),
        )
        for position, column in enumerate(COLUMNS)
        if not _is_header(values[position] if position < len(values) else None, column)
    ]
    if errors:
        raise ImportValidationError(errors)


def _is_header(value: object, column: ImportColumn) -> bool:
    return isinstance(value, str) and value.strip().casefold() == column.excel.header.casefold()


def _parse_row(row: int, cells: dict[str, Any]) -> tuple[ImportRow, list[ImportRowError]]:
    try:
        user = UserImportRow.model_validate(cells)
    except ValidationError as exc:
        errors = [ImportRowError(row, str(error["loc"][0]), error["msg"]) for error in exc.errors()]
        email = _valid_cell(_EMAIL_CELL, cells.get("email"))
        code = _valid_cell(_DEPARTMENT_CODE_CELL, cells.get("department_code"))
        return ImportRow(row, None, None if email is None else email.lower(), code), errors
    return ImportRow(row, user, user.email.lower(), user.department_code), []


def _valid_cell[T](adapter: TypeAdapter[T], value: object) -> T | None:
    """Giá trị đã chuẩn hóa của một ô, None khi ô trống hoặc sai."""
    if value is None:
        return None
    try:
        return adapter.validate_python(value)
    except ValidationError:
        return None


def _duplicate_email_errors(rows: Sequence[ImportRow]) -> list[ImportRowError]:
    """Email lặp lại trong file: lỗi ở các dòng sau, chỉ ra dòng đầu tiên có email đó."""
    first_rows: dict[str, int] = {}
    errors = []
    for row in rows:
        if row.email is None:
            continue
        first_row = first_rows.setdefault(row.email, row.row)
        if first_row != row.row:
            message = messages.IMPORT_EMAIL_DUPLICATED.format(row=first_row)
            errors.append(ImportRowError(row.row, "email", message))
    return errors
