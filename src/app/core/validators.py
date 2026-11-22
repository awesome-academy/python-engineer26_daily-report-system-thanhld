"""Validator và kiểu Pydantic dùng chung cho schema của các module."""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from app.core import messages
from app.core.constants import BIGINT_MAX, ID_MIN, INVISIBLE_UNICODE_CATEGORIES, KEYWORD_MAX_LENGTH


def reject_null[T](value: T | None) -> T:
    """Field bắt buộc trong schema cập nhật từng phần: không gửi thì giữ nguyên, gửi null thì 422.

    Dùng với `field_validator`, ví dụ `_not_null = field_validator("name")(reject_null)`. Validator
    chỉ chạy khi client có gửi field, nên field bỏ trống vẫn mang nghĩa "không đổi".
    """
    if value is None:
        raise ValueError(messages.NOT_NULL)
    return value


def reject_nul(value: str) -> str:
    """PostgreSQL không lưu, không so sánh được chuỗi chứa ký tự NUL: gửi xuống DB là lỗi 500."""
    if "\x00" in value:
        raise ValueError(messages.NUL_CHARACTER)
    return value


# Gắn vào mọi kiểu chuỗi tự do người dùng nhập rồi đi xuống DB (tên, mô tả, từ khóa tìm kiếm).
NoNul = AfterValidator(reject_nul)


def reject_invisible(value: str) -> str:
    """Tên hiển thị một dòng không chứa ký tự điều khiển, ký tự định dạng vô hình.

    `strip()` không bỏ các ký tự này: tên chỉ gồm khoảng trắng độ rộng 0 vẫn đủ độ dài tối thiểu
    nhưng hiện như rỗng ở danh sách, email ("Xin chào ,"), file Excel; ký tự đảo chiều văn bản làm
    tên hiển thị sai thứ tự (giả được tên khác); ký tự vô hình giữa tên làm tìm kiếm không khớp.
    Không dùng cho nội dung nhiều dòng (báo cáo, mô tả), nơi xuống dòng là hợp lệ.
    """
    if any(unicodedata.category(char) in INVISIBLE_UNICODE_CATEGORIES for char in value):
        raise ValueError(messages.INVISIBLE_CHARACTER)
    return value


NoInvisible = AfterValidator(reject_invisible)


def blank_to_none(value: str) -> str | None:
    """Field tùy chọn: chuỗi rỗng sau khi trim là "không có", lưu null như khi gửi null.

    Không vậy thì API có hai cách biểu diễn cùng một trạng thái ("" và null).
    """
    return value or None


def drop_duplicates(ids: list[int]) -> list[int]:
    """Danh sách id trong body: id gửi trùng là cùng một bản ghi, gộp lại và giữ thứ tự gửi.

    Để nguyên thì insert trùng khóa chính (người nhận báo cáo), API trả 500.
    """
    return list(dict.fromkeys(ids))


# Id bản ghi (path, query, body): ngoài phạm vi khóa chính bigint thì trả 422 ngay. Số lớn hơn mà
# gửi xuống DB thì asyncpg từ chối tham số, API trả 500.
Id = Annotated[int, Field(ge=ID_MIN, le=BIGINT_MAX)]
# Từ khóa tìm kiếm của danh sách. Chuỗi rỗng sau khi trim nghĩa là không lọc.
Keyword = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=KEYWORD_MAX_LENGTH), NoNul
]
