"""Lệnh `daily-report create-admin`."""

import asyncio
from typing import Annotated

import typer
from pydantic import ValidationError

from app.cli._db import cli_session, exit_with_validation_errors
from app.core.exceptions import AppError
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


async def _create_user(data: UserCreate) -> User:
    async with cli_session() as session:
        return await UserService(session).create_user(data)


def create_admin(
    email: Annotated[str, typer.Option(prompt=True, help="Email đăng nhập")],
    full_name: Annotated[str, typer.Option(prompt="Họ tên", help="Họ tên hiển thị")],
    password: Annotated[
        str,
        typer.Option(
            prompt="Mật khẩu",
            hide_input=True,
            confirmation_prompt="Nhập lại mật khẩu",
            envvar="ADMIN_PASSWORD",
            help=(
                "Tối thiểu 8 ký tự, có chữ thường, chữ hoa, chữ số, ký tự đặc biệt. "
                "Bỏ trống để nhập ẩn."
            ),
        ),
    ],
) -> None:
    """Tạo tài khoản admin để đăng nhập lần đầu."""
    try:
        data = UserCreate(email=email, full_name=full_name, password=password, role=UserRole.ADMIN)
        user = asyncio.run(_create_user(data))
    except ValidationError as exc:
        raise exit_with_validation_errors(exc) from exc
    except AppError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(f"Đã tạo admin #{user.id}: {user.email}", fg=typer.colors.GREEN)
