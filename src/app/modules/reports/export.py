"""File Excel báo cáo một ngày của các bộ phận manager quản lý (M5)."""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import IO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from app.core.clock import local_datetime
from app.core.constants import EXCEL_DATETIME_FORMAT
from app.core.excel import ExcelColumn, save_workbook, text_cell, write_header
from app.modules.reports.schemas import ReportExportRow


class SubmissionStatus(StrEnum):
    SUBMITTED = "Đã nộp"
    MISSING = "Chưa nộp"


# Tên nội dung báo cáo giống email S1.
COLUMNS = (
    ExcelColumn("Mã bộ phận", 14),
    ExcelColumn("Bộ phận", 24),
    ExcelColumn("Nhân viên", 24),
    ExcelColumn("Email", 30),
    ExcelColumn("Trạng thái", 12),
    ExcelColumn("Công việc dự định", 40),
    ExcelColumn("Công việc thực tế", 40),
    ExcelColumn("Lý do chưa hoàn thành", 30),
    ExcelColumn("Dự định ngày tiếp theo", 40),
    ExcelColumn("Giờ gửi", 18),
)
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
    sheet = workbook.create_sheet(title=report_date.isoformat())
    write_header(sheet, COLUMNS)
    for row in rows:
        sheet.append(_row_cells(sheet, row))
    return save_workbook(workbook)


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
