"""CLI quản trị. Xem lệnh: `uv run daily-report --help`.

Trong Docker: `docker compose exec api daily-report --help`.
"""

import typer

# Import kèm alias để tên hàm không che mất submodule app.cli.admin, app.cli.seed.
from app.cli.admin import create_admin as _create_admin
from app.cli.seed import seed as _seed

cli = typer.Typer(help="Lệnh quản trị Daily Report API.", no_args_is_help=True)
cli.command("create-admin")(_create_admin)
cli.command("seed")(_seed)
