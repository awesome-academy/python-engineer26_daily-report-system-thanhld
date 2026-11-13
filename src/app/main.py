"""Khởi tạo ứng dụng FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import models as _models  # noqa: F401 (nạp đủ model trước khi SQLAlchemy nối quan hệ)
from app.api.health import router as health_router
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.constants import LOCAL_STORAGE_URL_PATH, StorageBackend
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.redis import redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


def mount_local_storage(app: FastAPI, settings: Settings) -> None:
    """Backend local: API phục vụ file đã lưu (ảnh đại diện) tại LOCAL_STORAGE_URL_PATH.

    Không cần đăng nhập, như URL ký sẵn của S3: key có chuỗi ngẫu nhiên nên không đoán được.
    Chỉ phục vụ file thường trong thư mục (không liệt kê thư mục, không theo symlink ra ngoài).
    """
    if settings.storage_backend is not StorageBackend.LOCAL:
        return
    # Tạo sẵn: StaticFiles báo lỗi (500) cho mọi request nếu thư mục chưa có, tức trước lần upload
    # đầu tiên.
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        LOCAL_STORAGE_URL_PATH,
        StaticFiles(directory=settings.local_storage_dir),
        name="local_storage",
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    app = FastAPI(
        title=settings.app_name,
        version=version("daily-report-api"),
        description="Backend API cho hệ thống báo cáo công việc hằng ngày.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    mount_local_storage(app, settings)
    return app


app = create_app()
