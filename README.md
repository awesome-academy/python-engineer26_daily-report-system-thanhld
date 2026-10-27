# Daily Report API

Backend REST API cho hệ thống báo cáo công việc hằng ngày: nhân viên gửi báo cáo, manager theo dõi theo bộ phận, admin quản lý user và bộ phận, hệ thống tự gửi email.

Python 3.13 · FastAPI · PostgreSQL 17 · Redis 7 · SQLAlchemy 2 (async) · Alembic · Docker Compose.

## Chạy nhanh

Cần [Docker](https://docs.docker.com/get-docker/) và [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # tùy chọn, chỉ cần khi muốn đổi cổng
make dev               # build và chạy api, postgres, redis, mailpit
```

| Địa chỉ | Dùng để |
| --- | --- |
| http://localhost:8001/docs | Swagger UI, thử API |
| http://localhost:8001/health | Trạng thái API, DB, Redis |
| http://localhost:8026 | Mailpit: xem email hệ thống gửi khi dev |

Migration chạy tự động khi container `api` khởi động. Sửa code trong `src/` thì API tự reload.

## Phát triển trên máy host

```bash
make install    # cài dependency, git hook pre-commit
make services   # chỉ chạy postgres, redis, mailpit
make run        # chạy API trên máy host (dừng container api trước: docker compose stop api)
```

## Kiểm tra

```bash
make check      # ruff, mypy strict, pytest + coverage (giống CI)
```

Test chạy trên PostgreSQL thật, database riêng `daily_report_test` (tự tạo nếu chưa có), cần `make services` trước. Mỗi test rollback khi kết thúc.

## Lệnh hay dùng

| Lệnh | Việc |
| --- | --- |
| `make dev` / `make down` | Chạy / dừng toàn bộ stack |
| `make logs` | Xem log API |
| `make migrate` | Chạy migration tới bản mới nhất |
| `make migration m="add users table"` | Tạo migration từ model |
| `make format` | Tự sửa lint, format |
| `make help` | Liệt kê mọi lệnh |

## Tài liệu

| File | Nội dung |
| --- | --- |
| [docs/requirements.md](docs/requirements.md) | 15 chức năng, endpoint, kỹ thuật, câu hỏi cần PM chốt |
| [docs/architecture.md](docs/architecture.md) | Công nghệ, kiến trúc, cấu trúc thư mục, quyết định kỹ thuật |
| [docs/database.md](docs/database.md) | ERD, bảng, ràng buộc, index |
| [docs/api-design.md](docs/api-design.md) | Quy ước API, mã lỗi, 39 endpoint |
| [docs/progress/](docs/progress/) | Kế hoạch 10 ngày, báo cáo từng ngày |
