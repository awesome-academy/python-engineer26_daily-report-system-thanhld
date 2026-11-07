"""Lệnh `daily-report send-test-email`."""

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from kombu.exceptions import OperationalError
from pydantic import TypeAdapter, ValidationError

from app.cli._db import exit_with_validation_errors
from app.core.config import get_settings
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.tasks import send_email
from app.modules.users.schemas import Email

# Hiển thị trong email để phân biệt các lần gửi thử.
REQUESTED_AT_FORMAT = "%H:%M:%S %d/%m/%Y"


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
    try:
        send_email.delay(to_email, EmailTemplate.TEST, context)
    except OperationalError as exc:
        typer.secho(f"Không đẩy được task vào Redis: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(
        f"Đã đưa email thử tới {to_email} vào hàng đợi. Worker gửi xong thì kiểm tra hộp thư.",
        fg=typer.colors.GREEN,
    )
