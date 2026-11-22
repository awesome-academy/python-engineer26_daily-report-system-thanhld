"""Kịch bản demo (docs/demo.md) ghi cứng tài khoản, id của dữ liệu seed để người demo gõ theo.

Đổi dữ liệu mẫu (app.seed_data) mà quên kịch bản thì demo gọi nhầm id, đăng nhập sai tài khoản.
"""

import re
from pathlib import Path

from app.seed_data import DEPARTMENTS, USERS, SeedUser, seed_id

DEMO = Path(__file__).resolve().parents[2] / "docs" / "demo.md"
EMAIL_DOMAIN = "@example.com"
NO_DEPARTMENT = "—"
# Dòng bảng "Tài khoản và id": | id | `tên trước @example.com` | role | bộ phận | vai trong demo |
ACCOUNT_ROW = re.compile(r"^\| (\d+) \| `([^`]+)` \| (\w+) \| ([^|]+?) \|", re.MULTILINE)
# Ô bộ phận: mã, kèm id ở lần đầu nhắc tới bộ phận đó, ví dụ "DEV (id 1)".
DEPARTMENT_CELL = re.compile(r"^(\w+)(?: \(id (\d+)\))?$")


def _expected_department(user: SeedUser) -> tuple[str, str | None]:
    department = next((d for d in DEPARTMENTS if d.code == user.department_code), None)
    if department is None:
        return NO_DEPARTMENT, None
    return department.code, str(seed_id(department))


def test_demo_accounts_match_seed_data() -> None:
    rows = ACCOUNT_ROW.findall(DEMO.read_text(encoding="utf-8"))

    assert len(rows) == len(USERS)
    for (user_id, name, role, department_cell), user in zip(rows, USERS, strict=True):
        assert f"{name}{EMAIL_DOMAIN}" == user.email
        assert (user_id, role) == (str(seed_id(user)), user.role.value)
        code, department_id = _expected_department(user)
        if code == NO_DEPARTMENT:
            assert department_cell == NO_DEPARTMENT, user.email
            continue
        match = DEPARTMENT_CELL.match(department_cell)
        assert match is not None, department_cell
        assert match.group(1) == code, user.email
        assert match.group(2) in (None, department_id), user.email
