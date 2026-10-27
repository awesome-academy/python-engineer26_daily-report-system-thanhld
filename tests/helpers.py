"""Helper dùng chung cho test."""

import asyncio

from typer.testing import CliRunner, Result

from app.cli import cli

runner = CliRunner()


async def invoke(*args: str) -> Result:
    # Lệnh CLI tự chạy asyncio.run(), nên phải chạy ở thread khác event loop của test.
    def run() -> Result:
        return runner.invoke(cli, list(args))

    return await asyncio.to_thread(run)
