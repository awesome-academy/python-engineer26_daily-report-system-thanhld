# Kiến trúc

## Công nghệ

| Thành phần | Lựa chọn |
| --- | --- |
| Ngôn ngữ | Python 3.13 |
| Web framework | FastAPI, Uvicorn |
| Validate, cấu hình | Pydantic v2, pydantic-settings |
| Cơ sở dữ liệu | PostgreSQL 17 (`unaccent`, `pg_trgm`) |
| ORM, migration | SQLAlchemy 2.0 (API: asyncpg; worker: psycopg đồng bộ), Alembic |
| Xác thực | PyJWT, pwdlib (Argon2) |
| Cache, hàng đợi | Redis 7 |
| Tác vụ nền, lịch | Celery 5, Celery Beat |
| Email | smtplib, Jinja2; Mailpit khi dev |
| Excel | openpyxl |
| Lưu trữ file | Local (mặc định) hoặc S3, chọn qua cấu hình |
| CLI, seeder | Typer |
| Logging, debug | structlog (JSON khi production, dạng đọc được khi dev), request-id; debugpy |
| Kiểm thử | pytest, pytest-asyncio, httpx, pytest-cov |
| Chất lượng code | ruff (lint, format), mypy strict, pre-commit |
| Package, đóng gói | uv, Docker, Docker Compose |
| CI | GitHub Actions |

Thư viện của các ngày sau (PyJWT, Celery, openpyxl, …) chỉ thêm vào `pyproject.toml` khi bắt đầu dùng.

## Modular monolith

Một ứng dụng, triển khai một lần, chia module theo nghiệp vụ trong `src/app/modules/`: `auth`, `users`, `departments`, `reports`, `notifications`. Mỗi module dùng cùng một khuôn:

| File | Làm | Không làm |
| --- | --- | --- |
| `router.py` | Khai báo endpoint, kiểm tra role, gọi service, trả response | Chứa nghiệp vụ, truy vấn DB |
| `schemas.py` | Dữ liệu vào, ra (Pydantic) | Trả thẳng model DB ra API |
| `service.py` | Quy tắc nghiệp vụ, phạm vi quyền, transaction, đẩy task | Biết về HTTP (Request, status code) |
| `repository.py` | Truy vấn SQLAlchemy | Chứa quy tắc nghiệp vụ |
| `models.py` | Bảng, quan hệ, ràng buộc | Logic xử lý |
| `exceptions.py` | Lỗi nghiệp vụ có mã | |

Phụ thuộc một chiều: router → service → repository → model. Module này gọi module khác qua service. Service ném `AppError` (có mã lỗi), handler chung trong `core/exceptions.py` đổi thành response JSON.

## Cấu trúc thư mục

```
.
├── docs/                      # requirement, thiết kế, tiến độ
├── migrations/                # Alembic (async)
├── scripts/                   # seed dữ liệu, tạo admin
├── src/app/
│   ├── main.py                # create_app(): middleware, exception handler, router
│   ├── cli.py                 # Typer: create-admin, seed
│   ├── models.py              # import model của mọi module cho Alembic
│   ├── core/                  # dùng chung, không chứa nghiệp vụ
│   │   ├── config.py          # Settings từ biến môi trường
│   │   ├── database.py        # engine, session, Base, mixin
│   │   ├── exceptions.py      # AppError, ErrorCode, exception handler
│   │   ├── logging.py         # structlog, middleware request-id
│   │   ├── pagination.py      # PageParams, Page, paginate()
│   │   └── redis.py           # client Redis
│   ├── api/
│   │   ├── deps.py            # dependency dùng chung (DB session, Redis)
│   │   ├── health.py          # GET /health
│   │   └── v1.py              # gom router các module dưới /api/v1
│   └── modules/               # auth, users, departments, reports, notifications
└── tests/
    ├── conftest.py            # DB test, rollback sau mỗi test, HTTP client
    ├── unit/
    └── api/
```

## Luồng tạo báo cáo (Ngày 4, 6)

1. `POST /api/v1/me/reports` kèm JWT. Router kiểm tra token, role USER, validate body.
2. `ReportService` kiểm tra trùng ngày và người nhận hợp lệ, lưu báo cáo và người nhận trong 1 transaction, commit.
3. Sau commit mới đẩy task gửi mail vào Redis, để worker không đọc phải báo cáo chưa tồn tại.
4. API trả 201 ngay. Celery worker gửi mail, lỗi thì retry tối đa 3 lần.

## Quyết định kỹ thuật

| # | Quyết định | Lý do |
| --- | --- | --- |
| 1 | FastAPI thay vì Django REST Framework | Chỉ có API, không cần admin site. FastAPI async sẵn, Swagger tự sinh. |
| 2 | JWT + refresh token xoay vòng; thu hồi bằng blacklist Redis và `token_version` | Đăng xuất, đổi mật khẩu có hiệu lực ngay, không phải chờ access token hết hạn. |
| 3 | API dùng SQLAlchemy async, Celery worker dùng session đồng bộ riêng | Celery chạy đồng bộ; không chạy event loop bên trong task. |
| 4 | Nhóm API theo vai trò (`/me`, `/manager`, `/admin`) | Khớp requirement, service không rẽ nhánh theo role, test phân quyền đơn giản. |
| 5 | Import Excel đồng bộ, "tất cả hoặc không", tối đa 1.000 dòng | Quy mô nhỏ, đơn giản. Vượt giới hạn thì chuyển sang job nền. |
| 6 | Test chạy trên PostgreSQL thật (DB riêng), rollback sau mỗi test | Bắt được lỗi riêng của PostgreSQL (unaccent, partial index) mà SQLite bỏ sót. |

## Môi trường local

Cổng mặc định tránh trùng các service phổ biến đang chạy trên máy dev:

| Service | Cổng host |
| --- | --- |
| API | 8001 |
| PostgreSQL | 5433 |
| Redis | 6380 |
| Mailpit UI / SMTP | 8026 / 1026 |

Đổi được qua biến môi trường trong `.env` (xem `.env.example`).
