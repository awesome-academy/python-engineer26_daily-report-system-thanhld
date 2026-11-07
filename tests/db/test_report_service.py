from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.departments.models import Department, DepartmentManager
from app.modules.reports.exceptions import ReportAlreadyExistsError
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.reports.repository import ReportRepository
from app.modules.reports.schemas import ManagerReportListParams, ReportCreate, ReportSort
from app.modules.reports.service import ReportService
from app.modules.users.models import User, UserRole
from tests.factories import create_department, create_report, create_user
from tests.helpers import recorded_queries

TODAY = date(2026, 11, 9)
REPORT = ReportCreate(
    report_date=TODAY, planned_work="Làm API", actual_work="Xong API", next_day_plan="Viết test"
)


async def count_rows(session: AsyncSession, author_id: int) -> tuple[int, int]:
    # Nhận id thay vì User: rollback khi lỗi làm mọi object trong session hết hạn.
    reports = await session.scalar(
        select(func.count()).select_from(DailyReport).where(DailyReport.author_id == author_id)
    )
    recipients = await session.scalar(
        select(func.count())
        .select_from(ReportRecipient)
        .join(DailyReport)
        .where(DailyReport.author_id == author_id)
    )
    return reports or 0, recipients or 0


@pytest.fixture
async def manager(db_session: AsyncSession) -> User:
    return await create_user(db_session, role=UserRole.MANAGER)


@pytest.fixture
async def department(db_session: AsyncSession, manager: User) -> Department:
    return await create_department(db_session, managers=[manager])


@pytest.fixture
async def author(db_session: AsyncSession, department: Department) -> User:
    return await create_user(
        db_session, department=department, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )


async def commit_prepared_data(session: AsyncSession) -> None:
    # Service rollback khi lỗi: dữ liệu chuẩn bị phải commit trước (vào savepoint của test) để
    # rollback chỉ bỏ phần service ghi, phép đếm sau đó mới có nghĩa.
    await session.commit()


async def test_create_report_maps_concurrent_duplicate_to_already_exists(
    db_session: AsyncSession,
    author: User,
    department: Department,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Giả lập hai request cùng ngày: lúc kiểm tra, báo cáo của request kia chưa được commit."""
    await create_report(db_session, author=author, department=department, report_date=TODAY)
    await commit_prepared_data(db_session)
    author_id = author.id

    async def not_found(_: ReportRepository, __: int, ___: date) -> bool:
        return False

    monkeypatch.setattr(ReportRepository, "exists_for_date", not_found)

    with pytest.raises(ReportAlreadyExistsError):
        await ReportService(db_session).create_report(author, REPORT, today=TODAY)

    # Chỉ còn báo cáo có sẵn (không người nhận): báo cáo mới và người nhận đều không được lưu.
    assert await count_rows(db_session, author_id) == (1, 0)


async def test_report_and_recipients_are_saved_in_one_transaction(
    db_session: AsyncSession, author: User, manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lưu người nhận lỗi (sau khi báo cáo đã được insert) thì báo cáo cũng không được lưu."""
    await commit_prepared_data(db_session)
    author_id, manager_id = author.id, manager.id
    real_list_recipients = ReportRepository.list_recipients

    async def recipient_vanishes(self: ReportRepository, department_id: int) -> Sequence[User]:
        recipients = await real_list_recipients(self, department_id)
        # Xóa cứng người nhận sau bước kiểm tra: insert report_recipients vi phạm khóa ngoại.
        await self.session.execute(
            delete(User).where(User.id == manager_id),
            execution_options={"synchronize_session": False},
        )
        return recipients

    monkeypatch.setattr(ReportRepository, "list_recipients", recipient_vanishes)

    with pytest.raises(IntegrityError, match="fk_report_recipients_recipient_id_users"):
        await ReportService(db_session).create_report(author, REPORT, today=TODAY)

    assert await count_rows(db_session, author_id) == (0, 0)


# Đủ nhiều bộ phận, báo cáo để planner chọn theo thống kê thật, không phải bảng gần rỗng. Manager
# quản lý 1/20 bộ phận: lọc bộ phận (và ngày) bằng index. Test đỏ khi câu truy vấn có dạng không
# dùng được index, ví dụ bọc department_id trong hàm. Phạm vi chiếm phần lớn bảng mà không lọc ngày
# thì planner có thể chọn Seq Scan, đúng theo chi phí.
INDEX_DEPARTMENTS = 20
INDEX_AUTHORS_PER_DEPARTMENT = 5
INDEX_DAYS = 60


async def plan_of_department_reports(
    session: AsyncSession, manager_id: int, params: ManagerReportListParams
) -> str:
    """EXPLAIN của câu lấy trang báo cáo mà service thật chạy, cùng tham số."""
    with recorded_queries(session) as queries:
        await ReportService(session).list_department_reports(manager_id, params)
    statement, parameters = next(query for query in queries if "LIMIT" in query[0])
    connection = await session.connection()
    plan = await connection.exec_driver_sql(f"EXPLAIN {statement}", parameters)
    return "\n".join(row[0] for row in plan)


@pytest.mark.parametrize(
    "params",
    [
        ManagerReportListParams(),
        ManagerReportListParams(date_from=TODAY, date_to=TODAY),
        ManagerReportListParams(sort=ReportSort.AUTHOR_NAME),
    ],
    ids=["default", "date-range", "sort-by-author"],
)
async def test_manager_report_list_uses_department_date_index(
    db_session: AsyncSession, manager: User, params: ManagerReportListParams
) -> None:
    departments = [await create_department(db_session) for _ in range(INDEX_DEPARTMENTS)]
    for department in departments:
        for _ in range(INDEX_AUTHORS_PER_DEPARTMENT):
            await create_user(db_session, department=department)
    db_session.add(DepartmentManager(department_id=departments[0].id, user_id=manager.id))
    await db_session.execute(
        text(
            "INSERT INTO daily_reports "
            "(author_id, department_id, report_date, planned_work, actual_work, next_day_plan) "
            "SELECT u.id, u.department_id, CAST(:today AS date) - day, 'a', 'b', 'c' "
            "FROM users u CROSS JOIN generate_series(0, :days - 1) AS day "
            "WHERE u.department_id IS NOT NULL"
        ),
        {"today": TODAY, "days": INDEX_DAYS},
    )
    # ANALYZE thấy cả dòng chưa commit của chính transaction này.
    for table in ("daily_reports", "department_managers", "departments", "users"):
        await db_session.execute(text(f"ANALYZE {table}"))

    plan = await plan_of_department_reports(db_session, manager.id, params)

    assert "ix_daily_reports_department_date" in plan, plan
