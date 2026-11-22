from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Response
from starlette.routing import Mount

from app.core.config import Settings
from app.core.constants import LOCAL_STORAGE_URL_PATH, StorageBackend

FRONTEND_ORIGIN = "http://localhost:3000"


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


def cors_app(origins: list[str]) -> FastAPI:
    from app.main import add_cors  # noqa: PLC0415 (xem docstring của conftest)

    app = FastAPI()

    @app.get("/download")
    async def download() -> Response:
        return Response(headers={"Content-Disposition": 'attachment; filename="bao-cao.xlsx"'})

    add_cors(app, Settings(cors_origins=origins))
    return app


async def send(app: FastAPI, method: str, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.request(method, "/download", headers=headers)


def preflight(origin: str, method: str = "PATCH") -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "authorization, content-type, x-request-id",
    }


async def test_cors_preflight_allows_bearer_token_without_credentials() -> None:
    response = await send(cors_app([FRONTEND_ORIGIN]), "OPTIONS", preflight(FRONTEND_ORIGIN))

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    # API không dùng cookie: trình duyệt không được gửi kèm credentials sang origin khác.
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(preflight("https://evil.example"), id="unknown-origin"),
        pytest.param(preflight(FRONTEND_ORIGIN, method="TRACE"), id="unused-method"),
    ],
)
async def test_cors_preflight_rejects_what_is_not_allowed(headers: dict[str, str]) -> None:
    response = await send(cors_app([FRONTEND_ORIGIN]), "OPTIONS", headers)

    assert response.status_code == 400


async def test_cors_response_exposes_download_filename_and_request_id() -> None:
    response = await send(cors_app([FRONTEND_ORIGIN]), "GET", {"Origin": FRONTEND_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    exposed = response.headers["access-control-expose-headers"].split(", ")
    assert exposed == ["Content-Disposition", "X-Request-ID"]
    assert "access-control-allow-credentials" not in response.headers


def test_cors_is_off_without_configured_origins() -> None:
    assert cors_app([]).user_middleware == []
