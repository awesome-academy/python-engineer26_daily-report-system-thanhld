"""alembic.ini chỉ được chứa ký tự ASCII.

Alembic và logging.config.fileConfig (gọi trong migrations/env.py) đọc file này bằng encoding
mặc định của hệ điều hành, không theo UTF-8 mode. Trên Windows (cp1252), một chữ tiếng Việt làm
mọi lệnh alembic và cả pytest lỗi UnicodeDecodeError. Ghi chú tiếng Việt để ở env.py.
"""

from pathlib import Path

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_alembic_ini_is_ascii_only() -> None:
    lines = ALEMBIC_INI.read_text(encoding="utf-8").splitlines()
    non_ascii = [number for number, line in enumerate(lines, start=1) if not line.isascii()]

    assert non_ascii == []
