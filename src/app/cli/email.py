"""Lệnh `daily-report send-test-email`, `daily-report send-monthly-summary`."""

from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import typer
from celery import Task
from kombu.exceptions import OperationalError
from pydantic import TypeAdapter, ValidationError

from app.cli._db import exit_with_validation_errors
from app.core.clock import local_today
from app.core.config import get_settings
from app.core.constants import MONTH_FORMAT
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.tasks import send_email
from app.modules.reports.monthly_summary import resolve_month
from app.modules.reports.tasks import send_monthly_summaries
from app.modules.users.schemas import Email

# Hiển thị trong email để phân biệt các lần gửi thử.
REQUESTED_AT_FORMAT = "%H:%M:%S %d/%m/%Y"


def _enqueue(task: Task[Any, Any], *args: Any) -> None:
    """Đẩy task vào Redis; Redis lỗi thì báo và thoát mã 1."""
    try:
        task.delay(*args)
    except OperationalError as exc:
        typer.secho(f"Không đẩy được task vào Redis: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def send_test_email(
    to: Annotated[str, typer.Argument(help="Địa chỉ nhận email thử")],
) -> None:
    """Đẩy một email thử vào hàng đợi để kiểm tra Celery worker và SMTP (khi dev: Mailpit)."""
    try:
        to_email = TypeAdapter(Email).validate_python(to)
    except ValidationError as exc:
        raise exit_with_validation_errors(exc, field="to") from exc

    requested_at = datetime.now(UTC).astimezone(ZoneInfo(get_settings().timezone))
    context = {"requested_at": requested_at.strftime(REQUESTED_AT_FORMAT)}
    _enqueue(send_email, to_email, EmailTemplate.TEST, context)
    typer.secho(
        f"Đã đưa email thử tới {to_email} vào hàng đợi. Worker gửi xong thì kiểm tra hộp thư.",
        fg=typer.colors.GREEN,
    )


def send_monthly_summary(
    month: Annotated[
        str | None,
        typer.Option(help="Tháng đã kết thúc, dạng YYYY-MM. Bỏ trống: tháng trước"),
    ] = None,
) -> None:
    """Gửi email thống kê báo cáo tháng (S3) ngay, không chờ lịch 08:00 ngày 1 của Celery Beat.

    Đẩy cùng task Beat gọi vào hàng đợi. Manager đã nhận email của tháng đó thì không gửi lại.
    """
    try:
        first = resolve_month(month, local_today())
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    label = first.strftime(MONTH_FORMAT)
    _enqueue(send_monthly_summaries, label)
    typer.secho(
        f"Đã đưa email thống kê tháng {label} vào hàng đợi. Worker gửi xong thì kiểm tra hộp thư.",
        fg=typer.colors.GREEN,
    )
