"""CLI quản trị. Xem lệnh: `uv run daily-report --help`.

Trong Docker: `docker compose exec api daily-report --help`.
"""

import asyncio
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

cli = typer.Typer(help="Lệnh quản trị Daily Report API.", no_args_is_help=True)


@cli.callback()
def main() -> None:
    """Lệnh quản trị Daily Report API."""


async def _create_user(data: UserCreate) -> User:
    # Engine riêng không giữ kết nối: mỗi lệnh CLI chạy trong event loop riêng rồi kết thúc.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await UserService(session).create_user(data)
    finally:
        await engine.dispose()


@cli.command("create-admin")
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
            help="Tối thiểu 8 ký tự. Bỏ trống để nhập ẩn.",
        ),
    ],
) -> None:
    """Tạo tài khoản admin để đăng nhập lần đầu."""
    try:
        data = UserCreate(email=email, full_name=full_name, password=password, role=UserRole.ADMIN)
        user = asyncio.run(_create_user(data))
    except ValidationError as exc:
        for error in exc.errors():
            typer.secho(f"{error['loc'][0]}: {error['msg']}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except AppError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(f"Đã tạo admin #{user.id}: {user.email}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    cli()
