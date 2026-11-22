"""Truy cập chéo giữa hai bộ phận, mỗi bộ phận có manager riêng (OWASP API1).

Test của từng endpoint thường lấy "bộ phận khác" là bộ phận chưa có manager. Phạm vi viết sai thành
"mọi bộ phận có manager" (quên điều kiện manager trong `managed_department_ids`) thì các test đó vẫn
xanh. Ở đây hai bộ phận như nhau, mỗi bên một manager, một nhân viên, một báo cáo: mỗi người chỉ
thấy dữ liệu bên mình, id của bên kia trả 404 như id không tồn tại.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.departments.models import Department
from app.modules.reports.models import DailyReport
from app.modules.users.models import User, UserRole
from tests.factories import auth_headers, create_department, create_report, create_user
from tests.helpers import load_sheet

API = get_settings().api_v1_prefix
REPORT_DATE = date(2026, 3, 2)
# Cột email trong file export (mã bộ phận, bộ phận, nhân viên, email...).
EXPORT_EMAIL_COLUMN = 3


@dataclass(frozen=True)
class Branch:
    """Một bộ phận với manager của nó, một nhân viên và báo cáo của nhân viên đó."""

    department: Department
    manager: User
    employee: User
    report: DailyReport


async def create_branch(session: AsyncSession) -> Branch:
    manager = await create_user(session, role=UserRole.MANAGER)
    department = await create_department(session, managers=[manager])
    employee = await create_user(session, department=department)
    report = await create_report(
        session,
        author=employee,
        department=department,
        report_date=REPORT_DATE,
        recipients=[manager],
    )
    return Branch(department=department, manager=manager, employee=employee, report=report)


@pytest.fixture
async def mine(db_session: AsyncSession) -> Branch:
    return await create_branch(db_session)


@pytest.fixture
async def theirs(db_session: AsyncSession) -> Branch:
    return await create_branch(db_session)


ManagerList = tuple[str, Callable[[Branch], int]]
MANAGER_LISTS = [
    pytest.param(("/manager/departments", lambda b: b.department.id), id="departments"),
    pytest.param(("/manager/employees", lambda b: b.employee.id), id="employees"),
    pytest.param(("/manager/reports", lambda b: b.report.id), id="reports"),
]


@pytest.mark.parametrize("endpoint", MANAGER_LISTS)
async def test_manager_list_shows_only_own_departments(
    client: AsyncClient, mine: Branch, theirs: Branch, endpoint: ManagerList
) -> None:
    path, item_id = endpoint

    response = await client.get(f"{API}{path}", headers=auth_headers(mine.manager))

    assert [item["id"] for item in response.json()["data"]] == [item_id(mine)]


ManagerDetail = Callable[[Branch], str]
MANAGER_DETAILS = [
    pytest.param(lambda b: f"/manager/departments/{b.department.id}", id="department"),
    pytest.param(lambda b: f"/manager/departments/{b.department.id}/members", id="members"),
    pytest.param(lambda b: f"/manager/employees/{b.employee.id}", id="employee"),
    pytest.param(lambda b: f"/manager/reports/{b.report.id}", id="report"),
]


@pytest.mark.parametrize("path", MANAGER_DETAILS)
async def test_manager_opens_own_record_but_not_other_department(
    client: AsyncClient, mine: Branch, theirs: Branch, path: ManagerDetail
) -> None:
    headers = auth_headers(mine.manager)

    own = await client.get(f"{API}{path(mine)}", headers=headers)
    other = await client.get(f"{API}{path(theirs)}", headers=headers)

    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "NOT_FOUND"


async def test_export_has_only_employees_of_own_departments(
    client: AsyncClient, mine: Branch, theirs: Branch
) -> None:
    response = await client.get(
        f"{API}/manager/reports/export",
        params={"date": REPORT_DATE.isoformat()},
        headers=auth_headers(mine.manager),
    )

    rows = list(load_sheet(response).iter_rows(min_row=2, values_only=True))
    assert [row[EXPORT_EMAIL_COLUMN] for row in rows] == [mine.employee.email]


async def test_user_sees_recipients_and_reports_of_own_department_only(
    client: AsyncClient, mine: Branch, theirs: Branch
) -> None:
    headers = auth_headers(mine.employee)

    recipients = await client.get(f"{API}/me/recipients", headers=headers)
    other_report = await client.get(f"{API}/me/reports/{theirs.report.id}", headers=headers)

    assert [item["id"] for item in recipients.json()] == [mine.manager.id]
    assert other_report.status_code == 404
