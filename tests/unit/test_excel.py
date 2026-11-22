import re
import struct
import tracemalloc
import zlib
from collections.abc import Callable
from io import BytesIO
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core import excel
from app.core.constants import (
    BYTES_PER_MB,
    DOWNLOAD_CHUNK_BYTES,
    EXCEL_MAX_ROWS,
    XLSX_MEDIA_TYPE,
    ZIP_SIGNATURE,
)
from app.core.excel import iter_file, iter_xlsx_rows, save_workbook, text_cell, xlsx_response
from app.core.uploads import UnsupportedFileTypeError
from tests.helpers import capture_module_logs, xlsx_file

SHEET_XML = "xl/worksheets/sheet1.xml"
STYLES_XML = "xl/styles.xml"
WORKBOOK_XML = "xl/workbook.xml"
# Phần dữ liệu giấu sau nội dung thật của một phần trong zip (zip bomb khai thiếu dung lượng).
HIDDEN_BYTES = 64 * BYTES_PER_MB


def rewrite_zip(data: bytes, replace: dict[str, bytes]) -> bytes:
    """Chép file zip, thay nội dung các phần trong `replace` (giả lập file .xlsx bị hỏng)."""
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w") as target:
        for item in source.infolist():
            target.writestr(item, replace.get(item.filename, source.read(item.filename)))
    return output.getvalue()


def recompress(data: bytes, name: str, content: bytes, method: int) -> bytes:
    """Chép file zip, ghi lại phần `name` với `content` bằng phương thức nén `method`."""
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename == name:
                target.writestr(name, content, compress_type=method)
            else:
                target.writestr(item, source.read(item.filename))
    return output.getvalue()


def under_declared(data: bytes, name: str, hidden: int) -> bytes:
    """Phần `name` giấu thêm `hidden` byte sau nội dung thật nhưng khai `file_size`, CRC của riêng
    nội dung thật: CRC khớp nên file vẫn đọc được, tổng `file_size` khai báo vẫn nhỏ.
    """
    with ZipFile(BytesIO(data)) as archive:
        real = archive.read(name)
    patched = bytearray(recompress(data, name, real + bytes(hidden), ZIP_DEFLATED))
    with ZipFile(BytesIO(bytes(patched))) as archive:
        local_header = archive.getinfo(name).header_offset
    crc = zlib.crc32(real)
    # Local file header: CRC ở byte 14, file_size ở byte 22.
    struct.pack_into("<I", patched, local_header + 14, crc)
    struct.pack_into("<I", patched, local_header + 22, len(real))
    # Central directory: CRC ở byte 16, file_size ở byte 24.
    for position in central_directory_entries(patched, name):
        struct.pack_into("<I", patched, position + 16, crc)
        struct.pack_into("<I", patched, position + 24, len(real))
    return bytes(patched)


def central_directory_entries(data: bytearray, name: str) -> list[int]:
    """Vị trí bản ghi central directory của phần `name` (tên file bắt đầu từ byte 46)."""
    positions = []
    position = data.find(b"PK\x01\x02")
    while position >= 0:
        name_length = struct.unpack_from("<H", data, position + 28)[0]
        if data[position + 46 : position + 46 + name_length] == name.encode():
            positions.append(position)
        position = data.find(b"PK\x01\x02", position + 4)
    return positions


def zip_file(name: str, content: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "=1+1"),
        ("#REF!", "#REF!"),
        ("a\x00b\x07c\x1fd", "abcd"),
        # Ngoài khoảng ký tự XML: openpyxl không chặn, ghi ra là file hỏng.
        ("a\ufffeb\uffffc\ud800d", "abcd"),
        ("Dòng 1\n\tDòng 2", "Dòng 1\n\tDòng 2"),
    ],
    ids=["formula", "error-code", "control-chars", "xml-noncharacters", "tab-newline"],
)
def test_text_cell_keeps_user_text_as_plain_text(value: str, expected: str) -> None:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    sheet.append([text_cell(sheet, value)])

    saved = load_workbook(save_workbook(workbook)).active
    assert isinstance(saved, Worksheet)
    cell = saved["A1"]

    assert (cell.value, cell.data_type) == (expected, "s")


@pytest.mark.parametrize("value", [None, "", "\x07\x1b\uffff"])
def test_text_cell_leaves_empty_text_blank(value: str | None) -> None:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()

    assert text_cell(sheet, value).value is None


async def test_iter_file_reads_in_chunks_and_closes_file() -> None:
    content = b"x" * (DOWNLOAD_CHUNK_BYTES * 2 + 1)
    file = BytesIO(content)

    chunks = [chunk async for chunk in iter_file(file)]

    assert [len(chunk) for chunk in chunks] == [DOWNLOAD_CHUNK_BYTES, DOWNLOAD_CHUNK_BYTES, 1]
    assert file.closed


async def test_iter_file_closes_file_when_stream_is_closed_early() -> None:
    # Client ngắt: Starlette hủy việc gửi, asyncio đóng generator (aclose) khi thu gom nó.
    file = BytesIO(b"x" * (DOWNLOAD_CHUNK_BYTES + 1))
    chunks = iter_file(file)

    await anext(chunks)
    await chunks.aclose()

    assert file.closed


def test_xlsx_response_sets_download_headers() -> None:
    file = BytesIO(b"abc")
    file.read()

    response = xlsx_response(file, "bao-cao.xlsx")

    assert response.media_type == XLSX_MEDIA_TYPE
    assert response.headers["content-disposition"] == 'attachment; filename="bao-cao.xlsx"'
    assert response.headers["content-length"] == "3"
    # Đọc lại từ đầu dù con trỏ đang ở cuối.
    assert file.tell() == 0


def test_iter_xlsx_rows_keeps_blank_rows_and_pads_to_max_col() -> None:
    data = xlsx_file([["a", "b", "c"], [], ["x"]])

    assert list(iter_xlsx_rows(data, 2)) == [("a", "b"), (None, None), ("x", None)]


def broken_sheet() -> bytes:
    # Dòng đầu đọc được, XML hỏng ở giữa sheet: chế độ read-only chỉ phát hiện khi duyệt tới đó.
    data = xlsx_file([["tiêu đề"], *[[f"dòng {index}"] for index in range(50)]])
    with ZipFile(BytesIO(data)) as archive:
        sheet = archive.read(SHEET_XML)
    return rewrite_zip(data, {SHEET_XML: sheet[: len(sheet) // 2]})


@pytest.mark.parametrize(
    "data",
    [
        b"email,ho_ten\n",
        ZIP_SIGNATURE + b"khong-phai-zip",
        zip_file("word/document.xml", b"<w:document/>"),
        broken_sheet(),
    ],
    ids=["not-zip", "broken-zip", "zip-without-workbook", "broken-sheet-xml"],
)
def test_iter_xlsx_rows_rejects_non_xlsx_content(data: bytes) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        list(iter_xlsx_rows(data, 1))


def test_iter_xlsx_rows_reads_under_declared_entry_without_inflating_it() -> None:
    # zipfile bung cả khối nén rồi mới cắt theo file_size: file vẫn đọc được, cộng file_size khai
    # báo không chặn được, phần giấu nằm hết trong RAM nếu đưa thẳng file cho openpyxl.
    data = under_declared(xlsx_file([["a"]]), STYLES_XML, HIDDEN_BYTES)

    tracemalloc.start()
    try:
        rows = list(iter_xlsx_rows(data, 1))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert rows == [("a",)]
    assert peak < HIDDEN_BYTES // 4


@pytest.mark.parametrize("method", [ZIP_BZIP2, ZIP_LZMA], ids=["bzip2", "lzma"])
def test_iter_xlsx_rows_rejects_compression_excel_does_not_use(method: int) -> None:
    data = xlsx_file([["a"]])
    with ZipFile(BytesIO(data)) as archive:
        styles = archive.read(STYLES_XML)

    with pytest.raises(UnsupportedFileTypeError):
        list(iter_xlsx_rows(recompress(data, STYLES_XML, styles, method), 1))


def edit_sheet(data: bytes, edit: Callable[[bytes], bytes]) -> bytes:
    with ZipFile(BytesIO(data)) as archive:
        sheet = archive.read(SHEET_XML)
    edited = edit(sheet)
    assert edited != sheet
    return rewrite_zip(data, {SHEET_XML: edited})


def test_iter_xlsx_rows_reads_past_wrong_dimension_tag() -> None:
    # Công cụ tạo file có thể ghi sai thẻ <dimension>: read-only của openpyxl dừng ở đó, các dòng
    # sau bị bỏ mà không báo lỗi (import thiếu người).
    data = xlsx_file([[f"dòng {index}"] for index in range(1, 51)])
    wrong = edit_sheet(
        data, lambda sheet: re.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1:A3"', sheet)
    )

    rows = list(iter_xlsx_rows(wrong, 1))

    assert (len(rows), rows[-1]) == (50, ("dòng 50",))


def test_iter_xlsx_rows_rejects_row_beyond_excel_limit() -> None:
    # openpyxl chèn một dòng trống cho mỗi số dòng bị bỏ qua: không chặn thì file vài KB có dòng
    # số hàng tỷ chạy hàng giờ.
    far_row = str(EXCEL_MAX_ROWS + 1).encode()
    data = edit_sheet(
        xlsx_file([["tiêu đề"], ["dòng 2"]]),
        lambda sheet: sheet.replace(b'<row r="2"', b'<row r="' + far_row + b'"').replace(
            b'r="A2"', b'r="A' + far_row + b'"'
        ),
    )

    with pytest.raises(UnsupportedFileTypeError):
        list(iter_xlsx_rows(data, 1))


def fifty_rows() -> bytes:
    return xlsx_file([[f"dòng {index}"] for index in range(1, 51)])


def corrupt_compressed_sheet() -> bytes:
    # Hỏng giữa dữ liệu nén của sheet (file tải lên bị lỗi đường truyền, ổ đĩa).
    data = bytearray(fifty_rows())
    with ZipFile(BytesIO(bytes(data))) as archive:
        local_header = archive.getinfo(SHEET_XML).header_offset
    name_length, extra_length = struct.unpack_from("<HH", data, local_header + 26)
    start = local_header + 30 + name_length + extra_length
    for position in range(start + 20, start + 60):
        data[position] ^= 0xFF
    return bytes(data)


def missing_shared_string() -> bytes:
    # Ô trỏ tới chuỗi dùng chung số 999 trong khi file không có bảng chuỗi.
    return edit_sheet(
        fifty_rows(),
        lambda sheet: re.sub(
            rb'(<c r="A2") t="inlineStr"><is><t>[^<]*</t></is>', rb'\1 t="s"><v>999</v>', sheet
        ),
    )


def unknown_workbook_attribute() -> bytes:
    data = fifty_rows()
    with ZipFile(BytesIO(data)) as archive:
        workbook = archive.read(WORKBOOK_XML)
    edited = workbook.replace(b"<workbookView", b'<workbookView khongCo="1"')
    assert edited != workbook
    return rewrite_zip(data, {WORKBOOK_XML: edited})


def encrypted_sheet() -> bytes:
    # Bit 0 của cờ trong zip: phần đã mã hóa (local header byte 6, central directory byte 8).
    data = bytearray(fifty_rows())
    with ZipFile(BytesIO(bytes(data))) as archive:
        data[archive.getinfo(SHEET_XML).header_offset + 6] |= 1
    for position in central_directory_entries(data, SHEET_XML):
        data[position + 8] |= 1
    return bytes(data)


@pytest.mark.parametrize(
    "build",
    [corrupt_compressed_sheet, missing_shared_string, unknown_workbook_attribute, encrypted_sheet],
    ids=["corrupt-deflate", "missing-shared-string", "unknown-attribute", "encrypted"],
)
def test_iter_xlsx_rows_maps_corrupt_file_to_unsupported_type_and_logs_reason(
    build: Callable[[], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = capture_module_logs(monkeypatch, excel)

    with pytest.raises(UnsupportedFileTypeError):
        list(iter_xlsx_rows(build(), 1))

    assert [log["event"] for log in logs] == ["xlsx_unreadable"]
