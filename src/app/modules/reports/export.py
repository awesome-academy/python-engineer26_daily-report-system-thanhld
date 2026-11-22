"""File Excel báo cáo một ngày của các bộ phận manager quản lý (M5)."""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import IO, NamedTuple

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from app.core.clock import local_datetime
from app.core.constants import EXCEL_DATETIME_FORMAT
from app.core.excel import save_workbook, text_cell
from app.modules.reports.schemas import ReportExportRow


class SubmissionStatus(StrEnum):
    SUBMITTED = "Đã nộp"
    MISSING = "Chưa nộp"


class Column(NamedTuple):
    header: str
    # Độ rộng cột theo đơn vị của Excel (khoảng số ký tự).
    width: int


# Tên nội dung báo cáo giống email S1.
COLUMNS = (
    Column("Mã bộ phận", 14),
    Column("Bộ phận", 24),
    Column("Nhân viên", 24),
    Column("Email", 30),
    Column("Trạng thái", 12),
    Column("Công việc dự định", 40),
    Column("Công việc thực tế", 40),
    Column("Lý do chưa hoàn thành", 30),
    Column("Dự định ngày tiếp theo", 40),
    Column("Giờ gửi", 18),
)
# Giữ dòng tiêu đề khi cuộn.
FREEZE_BELOW_HEADER = "A2"
HEADER_FONT = Font(bold=True)
# Nhân viên chưa nộp: chữ đỏ đậm trên nền đỏ nhạt (kiểu "Bad" có sẵn của Excel).
MISSING_FONT = Font(bold=True, color="9C0006")
MISSING_FILL = PatternFill(fill_type="solid", fgColor="FFC7CE")
# Nội dung báo cáo nhiều dòng: xuống dòng trong ô, đọc từ trên xuống.
CONTENT_ALIGNMENT = Alignment(wrap_text=True, vertical="top")


def write_report_workbook(report_date: date, rows: Iterable[ReportExportRow]) -> IO[bytes]:
    """Ghi file Excel báo cáo ngày `report_date`, trả file tạm đã ghi xong (con trỏ ở đầu).

    Mỗi dòng một nhân viên, theo thứ tự của `rows`. Hàm chặn (openpyxl đồng bộ): gọi trong
    `asyncio.to_thread`.
    """
    workbook = Workbook(write_only=True)
    # Chế độ write-only: độ rộng cột, cố định tiêu đề phải đặt trước khi ghi dòng đầu tiên.
    sheet = workbook.create_sheet(title=report_date.isoformat())
    for index, column in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = column.width
    sheet.freeze_panes = FREEZE_BELOW_HEADER
    sheet.append([_header_cell(sheet, column.header) for column in COLUMNS])
    for row in rows:
        sheet.append(_row_cells(sheet, row))
    return save_workbook(workbook)


def _header_cell(sheet: WriteOnlyWorksheet, header: str) -> Cell:
    cell = text_cell(sheet, header)
    cell.font = HEADER_FONT
    return cell


def _row_cells(sheet: WriteOnlyWorksheet, row: ReportExportRow) -> list[Cell]:
    report = row.report
    if report is None:
        status = text_cell(sheet, SubmissionStatus.MISSING)
        status.font = MISSING_FONT
        status.fill = MISSING_FILL
        contents: tuple[str | None, ...] = (None, None, None, None)
        submitted_at = WriteOnlyCell(sheet)
    else:
        status = text_cell(sheet, SubmissionStatus.SUBMITTED)
        contents = (
            report.planned_work,
            report.actual_work,
            report.incomplete_reason,
            report.next_day_plan,
        )
        # Excel không lưu múi giờ: ghi giờ Việt Nam.
        submitted_at = WriteOnlyCell(sheet, local_datetime(report.created_at).replace(tzinfo=None))
        submitted_at.number_format = EXCEL_DATETIME_FORMAT
    content_cells = [text_cell(sheet, value) for value in contents]
    for cell in content_cells:
        cell.alignment = CONTENT_ALIGNMENT
    return [
        text_cell(sheet, row.department.code),
        text_cell(sheet, row.department.name),
        text_cell(sheet, row.author.full_name),
        text_cell(sheet, row.author.email),
        status,
        *content_cells,
        submitted_at,
    ]
