from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core.constants import DOWNLOAD_CHUNK_BYTES, XLSX_MEDIA_TYPE, ZIP_SIGNATURE
from app.core.excel import iter_file, iter_xlsx_rows, save_workbook, text_cell, xlsx_response
from app.core.uploads import UnsupportedFileTypeError
from tests.helpers import xlsx_file

SHEET_XML = "xl/worksheets/sheet1.xml"


def rewrite_zip(data: bytes, replace: dict[str, bytes]) -> bytes:
    """Chép file zip, thay nội dung các phần trong `replace` (giả lập file .xlsx bị hỏng)."""
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w") as target:
        for item in source.infolist():
            target.writestr(item, replace.get(item.filename, source.read(item.filename)))
    return output.getvalue()


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
