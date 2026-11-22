import re
import unicodedata

import pytest

from app.core import messages
from app.core.validators import reject_invisible


@pytest.mark.parametrize(
    "name",
    [
        "Nguyễn Văn An",
        # Dấu tiếng Việt dạng tổ hợp (NFD) là ký tự nhóm Mn, không phải ký tự vô hình.
        unicodedata.normalize("NFD", "Đặng Thị Ánh"),
        "Anne-Marie O'Brien",
        "Phòng Kỹ thuật & Vận hành",
    ],
)
def test_reject_invisible_accepts_visible_names(name: str) -> None:
    assert reject_invisible(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "\u200b",  # khoảng trắng độ rộng 0: trông như tên rỗng
        "\ufeffAn",  # BOM, hay dính khi chép từ file
        "Ngu\u200cyen",  # zero-width non-joiner: tìm "nguyen" không khớp
        "An\u202eneuyg",  # đảo chiều văn bản: hiển thị thành "Anguyen"
        "An\tB",  # tab giữa tên (strip chỉ bỏ ở hai đầu)
        "An\x1b[31m",  # mã điều khiển terminal
    ],
)
def test_reject_invisible_rejects_control_and_format_characters(name: str) -> None:
    with pytest.raises(ValueError, match=re.escape(messages.INVISIBLE_CHARACTER)):
        reject_invisible(name)
