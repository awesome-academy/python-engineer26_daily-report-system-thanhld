"""File Excel (.xlsx): ghi file tải về (ô chữ an toàn, file tạm, gửi từng đoạn), đọc file tải lên.

Ghi bằng openpyxl chế độ write-only: mỗi dòng ghi ra đĩa ngay khi thêm, không giữ cả bảng ô trong
RAM. Đọc bằng chế độ read-only: duyệt từng dòng, không dựng cả sheet thành object ô. openpyxl là thư
viện đồng bộ, hàm ghi, đọc file chạy trong `asyncio.to_thread`.
"""

import asyncio
import os
import re
from collections.abc import AsyncGenerator, Generator, Sequence
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import IO, Any, NamedTuple
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from fastapi import status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from app.core.constants import (
    DOWNLOAD_CHUNK_BYTES,
    EXCEL_SPOOL_MAX_BYTES,
    XLSX_MAX_UNCOMPRESSED_BYTES,
    XLSX_MAX_UNCOMPRESSED_MB,
    XLSX_MEDIA_TYPE,
    XML_ILLEGAL_CHARACTERS_PATTERN,
    ZIP_SIGNATURE,
)
from app.core.exceptions import AppError, ErrorCode
from app.core.uploads import UPLOAD_FIELD, UnsupportedFileTypeError

_XML_ILLEGAL_CHARACTERS = re.compile(XML_ILLEGAL_CHARACTERS_PATTERN)

# Response 200 trên Swagger của endpoint trả file .xlsx (mặc định FastAPI ghi là JSON).
XLSX_FILE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "File .xlsx",
        "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    }
}

# Lỗi zipfile, openpyxl ném ra khi nội dung không phải .xlsx hợp lệ: file hỏng (BadZipFile), zip
# không có workbook như file .docx (OSError), workbook trỏ tới phần không có (KeyError), XML hỏng
# (ParseError), giá trị sai trong XML (ValueError).
XLSX_READ_ERRORS = (BadZipFile, OSError, KeyError, ValueError, ParseError)


class XlsxTooLargeError(AppError):
    """File .xlsx (zip) giải nén ra quá lớn: cùng mã với file vượt dung lượng."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = ErrorCode.FILE_TOO_LARGE

    def __init__(self) -> None:
        super().__init__(
            f"Nội dung file .xlsx sau khi giải nén vượt quá {XLSX_MAX_UNCOMPRESSED_MB} MB. Chỉ giữ "
            "dữ liệu cần import, bỏ các sheet, ảnh không cần thiết.",
            details={"field": UPLOAD_FIELD, "max_uncompressed_bytes": XLSX_MAX_UNCOMPRESSED_BYTES},
        )


def iter_xlsx_rows(data: bytes, max_col: int) -> Generator[tuple[Any, ...]]:
    """Giá trị ô từng dòng của sheet đầu tiên, từ dòng 1, mỗi dòng đúng `max_col` ô.

    Dòng trống ở giữa vẫn có (toàn None), nên vị trí trong dãy là số dòng trên Excel. Ô công thức
    cho giá trị Excel đã tính lúc lưu file, không chạy công thức. Nội dung không phải .xlsx hợp lệ
    thì ném UnsupportedFileTypeError (415), kể cả khi lỗi nằm giữa sheet: chế độ read-only đọc XML
    dần theo dòng. Hàm chặn: duyệt trong `asyncio.to_thread`.
    """
    if not data.startswith(ZIP_SIGNATURE):
        raise UnsupportedFileTypeError((XLSX_MEDIA_TYPE,))
    try:
        with ZipFile(BytesIO(data)) as archive:
            # zipfile không giải nén một phần quá file_size khai trong zip (khai sai thì lỗi CRC),
            # nên cộng file_size là đủ chặn zip bomb.
            if sum(info.file_size for info in archive.infolist()) > XLSX_MAX_UNCOMPRESSED_BYTES:
                raise XlsxTooLargeError
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets[:1]:
                yield from sheet.iter_rows(max_col=max_col, values_only=True)
        finally:
            workbook.close()
    except XLSX_READ_ERRORS as exc:
        raise UnsupportedFileTypeError((XLSX_MEDIA_TYPE,)) from exc


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
