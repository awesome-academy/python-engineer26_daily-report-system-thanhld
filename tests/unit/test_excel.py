import struct
import tracemalloc
import zlib
from io import BytesIO
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core.constants import BYTES_PER_MB, DOWNLOAD_CHUNK_BYTES, XLSX_MEDIA_TYPE, ZIP_SIGNATURE
from app.core.excel import iter_file, iter_xlsx_rows, save_workbook, text_cell, xlsx_response
from app.core.uploads import UnsupportedFileTypeError
from tests.helpers import xlsx_file

SHEET_XML = "xl/worksheets/sheet1.xml"
STYLES_XML = "xl/styles.xml"
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
    # Central directory: CRC ở byte 16, file_size ở byte 24, tên file từ byte 46.
    position = patched.find(b"PK\x01\x02")
    while position >= 0:
        name_length = struct.unpack_from("<H", patched, position + 28)[0]
        if patched[position + 46 : position + 46 + name_length] == name.encode():
            struct.pack_into("<I", patched, position + 16, crc)
            struct.pack_into("<I", patched, position + 24, len(real))
        position = patched.find(b"PK\x01\x02", position + 4)
    return bytes(patched)


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
