from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core.constants import DOWNLOAD_CHUNK_BYTES, XLSX_MEDIA_TYPE
from app.core.excel import iter_file, save_workbook, text_cell, xlsx_response


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "=1+1"),
        ("#REF!", "#REF!"),
        ("a\x00b\x07c\x1fd", "abcd"),
        ("Dòng 1\n\tDòng 2", "Dòng 1\n\tDòng 2"),
    ],
    ids=["formula", "error-code", "control-chars", "tab-newline"],
)
def test_text_cell_keeps_user_text_as_plain_text(value: str, expected: str) -> None:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    sheet.append([text_cell(sheet, value)])

    saved = load_workbook(save_workbook(workbook)).active
    assert isinstance(saved, Worksheet)
    cell = saved["A1"]

    assert (cell.value, cell.data_type) == (expected, "s")


@pytest.mark.parametrize("value", [None, "", "\x07\x1b"])
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


async def test_iter_file_closes_file_when_client_disconnects() -> None:
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
