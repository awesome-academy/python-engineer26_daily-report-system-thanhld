"""Tìm kiếm chuỗi dùng chung cho danh sách: mẫu LIKE không dấu, không phân biệt hoa thường."""

from sqlalchemy import ColumnElement, func

from app.core.constants import LIKE_ESCAPE_CHAR

# "\\" đứng đầu để không escape lại dấu "\\" vừa chèn cho "%", "_".
_LIKE_SPECIAL = (LIKE_ESCAPE_CHAR, "%", "_")


def contains_pattern(keyword: str) -> ColumnElement[str]:
    """Mẫu LIKE '%từ khóa%' đã bỏ dấu, chữ thường, escape ký tự đặc biệt.

    Dùng với `.like(pattern, escape=LIKE_ESCAPE_CHAR)`. Escape làm trong SQL, sau unaccent:
    unaccent đổi ký tự full-width (U+FF05, U+FF3F, U+FF3C) thành "%", "_", "\\", nên escape trước
    khi bỏ dấu thì các ký tự này lại thành ký tự đại diện.
    """
    escaped = func.immutable_unaccent(func.lower(keyword))
    for char in _LIKE_SPECIAL:
        escaped = func.replace(escaped, char, LIKE_ESCAPE_CHAR + char)
    return func.concat("%", escaped, "%")
