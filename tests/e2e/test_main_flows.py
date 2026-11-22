"""Test end-to-end các luồng chính, đi qua API như client thật.

Khác test ở tests/api: request commit thật vào DB, task nền đi qua hàng đợi Redis rồi chạy như
worker, đọc dữ liệu đã commit bằng kết nối riêng. Chỉ SMTP được thay bằng hộp thư giả. Dữ liệu tạo
qua API, không qua factory; riêng admin đầu tiên tạo bằng lệnh CLI `create-admin` như khi triển
khai.
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import EMAIL_DATE_FORMAT, SETUP_PASSWORD_PATH, XLSX_MEDIA_TYPE
from app.modules.auth.tasks import send_account_setup_email
from app.modules.notifications.models import EmailStatus, EmailTemplate
from app.modules.notifications.rendering import RenderedEmail
from app.modules.reports.export import COLUMNS, SubmissionStatus
from app.modules.reports.tasks import send_report_notification
from app.modules.users.models import UserRole
from tests.factories import DEFAULT_PASSWORD
from tests.helpers import (
    FakeMailer,
    QueuedTask,
    bearer,
    email_logs,
    invoke,
    load_sheet,
    login,
    login_tokens,
    run_queued_tasks,
)

API = get_settings().api_v1_prefix
ADMIN_EMAIL = "admin@example.com"
DEPARTMENT = {"code": "DEV", "name": "Phòng Phát triển"}
MANAGER = {"email": "binh.tran@example.com", "full_name": "Trần Thị Bình", "role": UserRole.MANAGER}
# Theo thứ tự họ tên, cũng là thứ tự dòng trong file export.
EMPLOYEES = (
    {"email": "an.nguyen@example.com", "full_name": "Nguyễn Văn An"},
    {"email": "dung.pham@example.com", "full_name": "Phạm Thị Dung"},
)
REPORT = {
    "planned_work": "Làm API export Excel",
    "actual_work": "Xong API export Excel, viết test",
    "next_day_plan": "Làm import Excel",
}


@dataclass(frozen=True)
class Account:
    """Tài khoản đã đặt mật khẩu và đăng nhập: `headers` mang access token của người đó."""

    id: int
    email: str
    full_name: str
    headers: dict[str, str]


@dataclass(frozen=True)
class NewDepartment:
    """Bộ phận admin vừa dựng: tài khoản mới tạo chưa có mật khẩu, chưa đăng nhập được."""

    id: int
    manager: dict[str, Any]
    employees: list[dict[str, Any]]

    @property
    def accounts(self) -> list[dict[str, Any]]:
        """Tài khoản theo thứ tự admin tạo."""
        return [self.manager, *self.employees]


@dataclass(frozen=True)
class Team:
    """Bộ phận dựng xong qua API: mọi tài khoản đã đặt mật khẩu và đăng nhập."""

    department_id: int
    manager: Account
    employees: list[Account]


def json_of(response: Response, status_code: int = 200) -> Any:
    """Body JSON sau khi kiểm tra mã trạng thái; sai mã thì in body để biết lỗi gì."""
    assert response.status_code == status_code, response.text
    return response.json()


async def sign_in_first_admin(client: AsyncClient) -> dict[str, str]:
    """Tạo admin đầu tiên bằng CLI như `make admin`, rồi đăng nhập qua API."""
    result = await invoke(
        "create-admin",
        *("--email", ADMIN_EMAIL),
        *("--full-name", "Quản Trị Viên"),
        *("--password", DEFAULT_PASSWORD),
    )
    assert result.exit_code == 0, result.output
    tokens = await login_tokens(client, ADMIN_EMAIL)
    return bearer(tokens["access_token"])


async def admin_builds_department(client: AsyncClient, admin: dict[str, str]) -> NewDepartment:
    """Admin tạo bộ phận, tài khoản manager và nhân viên của bộ phận, rồi gán manager."""
    department = json_of(
        await client.post(f"{API}/admin/departments", json=DEPARTMENT, headers=admin), 201
    )
    manager = json_of(await client.post(f"{API}/admin/users", json=MANAGER, headers=admin), 201)
    employees = [
        json_of(
            await client.post(
                f"{API}/admin/users",
                json={**employee, "department_id": department["id"]},
                headers=admin,
            ),
            201,
        )
        for employee in EMPLOYEES
    ]
    json_of(
        await client.post(
            f"{API}/admin/departments/{department['id']}/managers",
            json={"user_id": manager["id"]},
            headers=admin,
        )
    )
    return NewDepartment(department["id"], manager, employees)


def setup_token(email: RenderedEmail) -> str:
    """Token trong link đặt mật khẩu của email, như khi user mở link."""
    [link] = [
        url
        for match in re.finditer(r"https?://\S+", email.text)
        if (url := urlsplit(match.group())).path.endswith(SETUP_PASSWORD_PATH)
    ]
    [token] = parse_qs(link.query)["token"]
    return token


async def sign_in_from_setup_email(
    client: AsyncClient, account: dict[str, Any], mailbox: FakeMailer
) -> Account:
    """User mở link trong email đặt mật khẩu gửi cho mình, đặt mật khẩu rồi đăng nhập."""
    [email] = [email for to_email, email in mailbox.sent if to_email == account["email"]]
    response = await client.post(
        f"{API}/auth/setup-password",
        json={"token": setup_token(email), "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 204, response.text
    tokens = await login_tokens(client, account["email"])
    return Account(
        account["id"], account["email"], account["full_name"], bearer(tokens["access_token"])
    )


async def build_team(client: AsyncClient, redis: Redis, mailbox: FakeMailer) -> Team:
    """Dựng bộ phận qua API như luồng của admin; mọi tài khoản đặt mật khẩu qua email, đăng nhập."""
    department = await admin_builds_department(client, await sign_in_first_admin(client))
    await run_queued_tasks(redis)
    manager, *employees = [
        await sign_in_from_setup_email(client, account, mailbox) for account in department.accounts
    ]
    return Team(department.id, manager, employees)


async def test_admin_builds_department_and_new_accounts_sign_in_from_emailed_link(
    e2e_client: AsyncClient, redis: Redis, mailbox: FakeMailer, engine: AsyncEngine
) -> None:
    client = e2e_client
    admin = await sign_in_first_admin(client)

    department = await admin_builds_department(client, admin)

    # Admin thấy đúng manager và thành viên của bộ phận.
    department_url = f"{API}/admin/departments/{department.id}"
    managers = json_of(await client.get(f"{department_url}/managers", headers=admin))
    assert [user["id"] for user in managers["data"]] == [department.manager["id"]]
    members = json_of(await client.get(f"{department_url}/members", headers=admin))
    assert [user["id"] for user in members["data"]] == [user["id"] for user in department.employees]
    # Tài khoản admin tạo chưa có mật khẩu: chưa đăng nhập được.
    response = await login(client, department.manager["email"], DEFAULT_PASSWORD)
    assert response.status_code == 401

    # Mỗi tài khoản mới có một email đặt mật khẩu trên hàng đợi; worker gửi tới đúng người.
    tasks = await run_queued_tasks(redis)
    assert tasks == [
        QueuedTask(send_account_setup_email.name, [account["id"]], {})
        for account in department.accounts
    ]
    emails = [account["email"] for account in department.accounts]
    assert [to_email for to_email, _ in mailbox.sent] == emails
    assert await email_logs(engine) == [
        (email, EmailStatus.SENT, EmailTemplate.ACCOUNT_SETUP) for email in emails
    ]

    # Đặt mật khẩu bằng link trong email rồi đăng nhập: manager thấy bộ phận mình quản lý, nhân
    # viên thấy manager trong danh sách người nhận báo cáo.
    manager, *employees = [
        await sign_in_from_setup_email(client, account, mailbox) for account in department.accounts
    ]
    managed = json_of(await client.get(f"{API}/manager/departments", headers=manager.headers))
    assert [item["id"] for item in managed["data"]] == [department.id]
    for employee in employees:
        recipients = json_of(await client.get(f"{API}/me/recipients", headers=employee.headers))
        assert [user["id"] for user in recipients] == [manager.id]


async def test_employee_report_emails_manager_who_reviews_and_exports_it(
    e2e_client: AsyncClient, redis: Redis, mailbox: FakeMailer, engine: AsyncEngine
) -> None:
    client = e2e_client
    team = await build_team(client, redis, mailbox)
    author, absent = team.employees
    manager = team.manager
    mailbox.sent.clear()
    today = local_today()

    report = json_of(
        await client.post(
            f"{API}/me/reports",
            json={**REPORT, "report_date": today.isoformat(), "recipient_ids": [manager.id]},
            headers=author.headers,
        ),
        201,
    )

    # Email báo cáo mới nằm trên hàng đợi; worker gửi cho manager kèm nội dung báo cáo.
    tasks = await run_queued_tasks(redis)
    assert tasks == [QueuedTask(send_report_notification.name, [report["id"]], {})]
    [(to_email, email)] = mailbox.sent
    assert to_email == manager.email
    assert today.strftime(EMAIL_DATE_FORMAT) in email.subject
    assert author.full_name in email.subject
    assert REPORT["actual_work"] in email.text
    assert (await email_logs(engine))[-1] == (
        manager.email,
        EmailStatus.SENT,
        EmailTemplate.REPORT_CREATED,
    )
    # Manager thấy báo cáo trong danh sách, mở xem chi tiết.
    listed = json_of(await client.get(f"{API}/manager/reports", headers=manager.headers))
    assert [item["id"] for item in listed["data"]] == [report["id"]]
    detail = json_of(
        await client.get(f"{API}/manager/reports/{report['id']}", headers=manager.headers)
    )
    assert detail["author"]["id"] == author.id
    assert {field: detail[field] for field in REPORT} == REPORT
    assert [user["id"] for user in detail["recipients"]] == [manager.id]
    # Export ngày hôm nay: người đã nộp kèm nội dung, người chưa nộp được đánh dấu.
    response = await client.get(
        f"{API}/manager/reports/export",
        params={"report_date": today.isoformat()},
        headers=manager.headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    header, *rows = load_sheet(response).iter_rows(values_only=True)
    assert header == tuple(column.header for column in COLUMNS)
    department = (DEPARTMENT["code"], DEPARTMENT["name"])
    # Bỏ cột cuối (giờ gửi): thời điểm thật lúc chạy test.
    assert [row[:-1] for row in rows] == [
        (
            *department,
            author.full_name,
            author.email,
            SubmissionStatus.SUBMITTED,
            REPORT["planned_work"],
            REPORT["actual_work"],
            None,
            REPORT["next_day_plan"],
        ),
        (*department, absent.full_name, absent.email, SubmissionStatus.MISSING, *[None] * 4),
    ]
    # Người viết thấy báo cáo trong lịch sử của mình.
    history = json_of(await client.get(f"{API}/me/reports", headers=author.headers))
    assert [item["id"] for item in history["data"]] == [report["id"]]
