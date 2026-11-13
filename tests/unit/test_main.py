from pathlib import Path

from fastapi import FastAPI
from starlette.routing import Mount

from app.core.config import Settings
from app.core.constants import LOCAL_STORAGE_URL_PATH, StorageBackend


async def test_lifespan_closes_connections_on_shutdown(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pass


def mounted_paths(app: FastAPI) -> list[str]:
    return [route.path for route in app.routes if isinstance(route, Mount)]


def test_local_storage_is_served_and_directory_created(tmp_path: Path) -> None:
    from app.main import mount_local_storage  # noqa: PLC0415 (xem docstring của conftest)

    app = FastAPI()
    storage_dir = tmp_path / "media"

    mount_local_storage(app, Settings(local_storage_dir=storage_dir))

    assert mounted_paths(app) == [LOCAL_STORAGE_URL_PATH]
    assert storage_dir.is_dir()


def test_s3_storage_is_not_served_by_api(tmp_path: Path) -> None:
    from app.main import mount_local_storage  # noqa: PLC0415 (xem docstring của conftest)

    app = FastAPI()
    settings = Settings(
        storage_backend=StorageBackend.S3, s3_bucket="daily-report", local_storage_dir=tmp_path
    )

    mount_local_storage(app, settings)

    assert mounted_paths(app) == []
