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
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import Settings, get_settings
from app.core.constants import (
    CORS_ALLOW_HEADERS,
    CORS_ALLOW_METHODS,
    CORS_EXPOSE_HEADERS,
    LOCAL_STORAGE_URL_PATH,
    MAX_PAGE_SIZE,
    REQUEST_BODY_MAX_BYTES,
    REQUEST_BODY_MAX_MB,
    StorageBackend,
)
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import REQUEST_ID_HEADER, RequestContextMiddleware, configure_logging
from app.core.redis import redis_client
from app.modules.reports.schemas import EXAMPLE_REPORT_DATE
from app.seed_data import (
    EXAMPLE_ADMIN,
    EXAMPLE_DEPARTMENT,
    EXAMPLE_EMPLOYEE,
    EXAMPLE_MANAGER,
    EXAMPLE_PASSWORD,
    seed_id,
)

_SAMPLE_ACCOUNTS = ", ".join(
    f"`{user.email}` ({user.role})" for user in (EXAMPLE_ADMIN, EXAMPLE_MANAGER, EXAMPLE_EMPLOYEE)
)
# Phần đầu trang Swagger (Markdown): cách thử nhanh và quy ước chung, chi tiết ở docs/api-design.md.
API_DESCRIPTION = f"""\
Backend API cho hệ thống báo cáo công việc hằng ngày: nhân viên gửi báo cáo, manager theo dõi \
theo bộ phận, admin quản lý user và bộ phận.

**Thử nhanh**

1. Tạo dữ liệu mẫu: `docker compose exec api daily-report seed --password {EXAMPLE_PASSWORD}`.
2. Bấm **Authorize**, ô `username` nhập email, ô `password` nhập mật khẩu ở bước 1: \
{_SAMPLE_ACCOUNTS}.
3. Gọi endpoint của role đó: nhóm `/admin` cho ADMIN, `/manager` cho MANAGER, `/me/reports` \
cho USER; `/me` cho mọi role.

Ví dụ request, response dùng dữ liệu mẫu: seed vào DB trống thì bộ phận {EXAMPLE_DEPARTMENT.code} \
có id {seed_id(EXAMPLE_DEPARTMENT)}, `{EXAMPLE_MANAGER.email}` id {seed_id(EXAMPLE_MANAGER)}, \
`{EXAMPLE_EMPLOYEE.email}` id {seed_id(EXAMPLE_EMPLOYEE)}. Ngày trong ví dụ cố định \
(`{EXAMPLE_REPORT_DATE}`): thử tạo báo cáo thì đổi `report_date` thành hôm nay (seed không tạo báo \
cáo hôm nay). Ví dụ không hiện field có giá trị `null` (FastAPI bỏ `null` khi xuất OpenAPI): field \
nào nhận, trả `null` xem ở tab Schema.

**Quy ước**

- Lỗi: `{{"error": {{"code": ..., "message": ..., "details": ...}}}}`, client xử lý theo `code`. \
Mỗi endpoint có ví dụ cho từng mã lỗi ở phần Responses.
- Lỗi validate (422): `details` là danh sách `{{"field": ..., "message": ...}}`, `field` có \
tiền tố vị trí (`body.`, `query.`, `path.`). Ví dụ 422 giống nhau ở mọi endpoint, chỉ minh họa \
format.
- Body của mọi request tối đa {REQUEST_BODY_MAX_MB} MB, lớn hơn thì trả 413 `REQUEST_TOO_LARGE` \
trước khi tới endpoint (nên không nằm trong ví dụ lỗi của từng endpoint).
- Danh sách có phân trang: query `page`, `page_size` (tối đa {MAX_PAGE_SIZE}), response \
`{{"data": [...], "meta": {{"page": ..., "page_size": ..., "total": ...}}}}`.
- Ngày báo cáo theo giờ Việt Nam (`2026-11-09`); thời điểm theo UTC, ISO 8601 \
(`2026-11-09T10:15:03.123456Z`).
"""


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


def add_cors(app: FastAPI, settings: Settings) -> None:
    """Cho frontend ở origin trong CORS_ORIGINS gọi API. Không cấu hình thì không thêm middleware.

    Không bật `allow_credentials`: API xác thực bằng header Authorization, không dùng cookie. Bật
    cùng origin "*" thì Starlette trả lại đúng origin của trang gọi kèm Allow-Credentials, sau này
    thêm cookie là trang nào cũng gọi được API bằng phiên của người dùng.
    """
    if not settings.cors_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=CORS_ALLOW_METHODS,
        allow_headers=[*CORS_ALLOW_HEADERS, REQUEST_ID_HEADER],
        expose_headers=[*CORS_EXPOSE_HEADERS, REQUEST_ID_HEADER],
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    app = FastAPI(
        title=settings.app_name,
        version=version("daily-report-api"),
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )

    # Middleware thêm sau bọc ngoài middleware thêm trước. Giới hạn body ở trong cùng: response 413
    # vẫn có request-id, header CORS và dòng log như mọi response.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=REQUEST_BODY_MAX_BYTES)
    app.add_middleware(RequestContextMiddleware)
    # Ngoài cùng: response lỗi (401, 413...) cũng có header CORS để frontend đọc được.
    add_cors(app, settings)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    mount_local_storage(app, settings)
    return app


app = create_app()
