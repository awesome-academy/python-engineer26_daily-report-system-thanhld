"""File Excel (.xlsx) tải về: ô chữ an toàn, lưu workbook ra file tạm, gửi file từng đoạn.

Ghi bằng openpyxl chế độ write-only: mỗi dòng ghi ra đĩa ngay khi thêm, không giữ cả bảng ô trong
RAM. openpyxl là thư viện đồng bộ, hàm ghi file chạy trong `asyncio.to_thread`.
"""

import asyncio
import os
import re
from collections.abc import AsyncGenerator, Sequence
from tempfile import SpooledTemporaryFile
from typing import IO, Any, NamedTuple

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from app.core.constants import (
    DOWNLOAD_CHUNK_BYTES,
    EXCEL_SPOOL_MAX_BYTES,
    XLSX_MEDIA_TYPE,
    XML_ILLEGAL_CHARACTERS_PATTERN,
)

_XML_ILLEGAL_CHARACTERS = re.compile(XML_ILLEGAL_CHARACTERS_PATTERN)

# Response 200 trên Swagger của endpoint trả file .xlsx (mặc định FastAPI ghi là JSON).
XLSX_FILE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "File .xlsx",
        "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    }
}


def text_cell(sheet: WriteOnlyWorksheet, value: str | None) -> Cell:
    """Ô chữ từ dữ liệu người dùng nhập: luôn hiện đúng chữ đã nhập, không bao giờ thành công thức.

    openpyxl tự coi chuỗi bắt đầu bằng "=" là công thức và "#N/A", "#REF!"… là ô lỗi: nội dung báo
    cáo "=HYPERLINK(...)" sẽ chạy khi mở file (formula injection). Ký tự XML của file không chứa
    được thì bỏ đi: ký tự điều khiển làm openpyxl báo lỗi (500), còn U+FFFE, U+FFFF openpyxl không
    chặn mà ghi ra file hỏng (Excel báo cần sửa file).
    """
    text = _XML_ILLEGAL_CHARACTERS.sub("", value) if value else None
    if not text:
        return WriteOnlyCell(sheet, None)
    cell = WriteOnlyCell(sheet, text)
    cell.data_type = "s"
    return cell


class ExcelColumn(NamedTuple):
    header: str
    # Độ rộng cột theo đơn vị của Excel (khoảng số ký tự).
    width: int
    # Định dạng ô của cả cột: Excel áp cho ô người dùng gõ vào sau này. None là mặc định.
    number_format: str | None = None


HEADER_FONT = Font(bold=True)
# Giữ dòng tiêu đề khi cuộn.
FREEZE_BELOW_HEADER = "A2"


def write_header(sheet: WriteOnlyWorksheet, columns: Sequence[ExcelColumn]) -> None:
    """Độ rộng, định dạng từng cột và dòng tiêu đề in đậm, cố định khi cuộn.

    Chế độ write-only: gọi trước khi ghi dòng nào khác (cột, cố định tiêu đề phải đặt trước).
    """
    # Stub types-openpyxl thiếu column_dimensions của WriteOnlyWorksheet; lúc chạy có (openpyxl
    # dựng giống Worksheet).
    dimensions = sheet.column_dimensions  # type: ignore[attr-defined]
    for index, column in enumerate(columns, start=1):
        dimension = dimensions[get_column_letter(index)]
        dimension.width = column.width
        if column.number_format is not None:
            dimension.number_format = column.number_format
    sheet.freeze_panes = FREEZE_BELOW_HEADER
    header_cells = [text_cell(sheet, column.header) for column in columns]
    for cell in header_cells:
        cell.font = HEADER_FONT
    sheet.append(header_cells)


def save_workbook(workbook: Workbook) -> IO[bytes]:
    """Lưu workbook ra file tạm (nhỏ thì nằm trong RAM), con trỏ ở đầu file, sẵn để gửi đi."""
    file = SpooledTemporaryFile(max_size=EXCEL_SPOOL_MAX_BYTES)  # noqa: SIM115 (trả file cho người gọi)
    workbook.save(file)
    file.seek(0)
    return file


async def iter_file(file: IO[bytes]) -> AsyncGenerator[bytes]:
    """Đọc file từng đoạn cho StreamingResponse; đóng (xóa file tạm) khi gửi xong, dừng giữa chừng.

    Client ngắt thì Starlette chỉ hủy việc gửi, không đóng generator; asyncio đóng nó (chạy tới
    `finally`) khi thu gom. File tạm không đóng thì cũng bị xóa khi object bị thu gom.
    """
    try:
        while chunk := await asyncio.to_thread(file.read, DOWNLOAD_CHUNK_BYTES):
            yield chunk
    finally:
        file.close()


def xlsx_response(file: IO[bytes], filename: str) -> StreamingResponse:
    """Response tải file .xlsx đã ghi xong, gửi từng đoạn; có Content-Length để client biết tiến độ.

    `filename` chỉ gồm ký tự ASCII (không cần mã hóa trong header).
    """
    size = file.seek(0, os.SEEK_END)
    file.seek(0)
    return StreamingResponse(
        iter_file(file),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size),
        },
    )
