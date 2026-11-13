# Daily Report API

Backend REST API cho hệ thống báo cáo công việc hằng ngày: nhân viên gửi báo cáo, manager theo dõi theo bộ phận, admin quản lý user và bộ phận, hệ thống tự gửi email.

Python 3.13 · FastAPI · PostgreSQL 17 · Redis 7 · SQLAlchemy 2 (async) · Alembic · Celery · Docker Compose.

## Chạy nhanh

Cần [Docker](https://docs.docker.com/get-docker/) và [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # tùy chọn, chỉ cần khi muốn đổi cổng
make dev               # build và chạy api, worker, postgres, redis, mailpit
```

| Địa chỉ | Dùng để |
| --- | --- |
| http://localhost:8001/docs | Swagger UI, thử API |
| http://localhost:8001/health | Trạng thái API, DB, Redis |
| http://localhost:8026 | Mailpit: xem email hệ thống gửi khi dev |

Migration chạy tự động khi container `api` khởi động. Sửa code trong `src/` thì API tự reload.

## Đăng nhập thử

```bash
docker compose exec api daily-report create-admin   # hoặc: make admin (chạy trên máy host)
```

Mật khẩu tối thiểu 8 ký tự, có chữ thường, chữ hoa, chữ số và ký tự đặc biệt (ví dụ `Matkhau@123`).

1. Mở Swagger http://localhost:8001/docs, bấm **Authorize**.
2. Ô `username` nhập email, ô `password` nhập mật khẩu vừa tạo.
3. Gọi `GET /api/v1/me`.

Đăng nhập theo chuẩn OAuth2 password flow, trả access token JWT (hết hạn sau 15 phút) và refresh token (7 ngày). Gọi `POST /api/v1/auth/refresh` để lấy cặp token mới, `POST /api/v1/auth/logout` để đăng xuất. Sai mật khẩu quá 5 lần trong 15 phút thì bị khóa tạm (429). `PATCH /api/v1/me` sửa hồ sơ, `PUT /api/v1/me/password` đổi mật khẩu (các phiên đăng nhập khác bị đăng xuất).

## Debug

**Debug API chạy trong Docker:**

1. Chạy `make debug` (tương đương `DEBUGPY=1 docker compose up -d --build`). API chạy dưới debugpy, mở cổng 5678 chỉ trên `127.0.0.1` của máy host (máy khác trong mạng LAN không attach được).
2. Trong VS Code, mở tab Run and Debug, chọn **Docker: attach API (debugpy)**, rồi đặt breakpoint trong `src/`.
3. Gọi API từ Swagger, chương trình sẽ dừng ở breakpoint.

- Muốn debug từ lúc API khởi động thì thêm `DEBUGPY_WAIT=1`. API sẽ chờ VS Code attach rồi mới chạy.
- Ở chế độ debug, API không tự reload khi sửa code. Chạy `make dev` để quay lại chế độ thường.

**Chạy và debug trên máy host:** dùng cấu hình **Local: API (uvicorn)** hoặc **Local: pytest file đang mở** trong `.vscode/launch.json`.

**Log:** mỗi request có một dòng log kèm `request_id`, và header `X-Request-ID` trên response có cùng giá trị. Dùng giá trị này để tìm log của request đang lỗi: `make logs | grep <request_id>`.

## Email

API không gửi email trực tiếp: đẩy task vào Redis, Celery worker (container `worker`) dựng nội dung từ template Jinja2 (`src/app/modules/notifications/templates/`), gửi qua SMTP, ghi kết quả vào bảng `email_logs`. Lỗi kết nối, lỗi SMTP thì thử lại tối đa 3 lần (chờ 30s, 60s, 120s); vẫn lỗi thì ghi `FAILED` kèm lý do.

Email hệ thống gửi: báo cáo mới cho người nhận (S1, sau `POST /api/v1/me/reports`).

Gửi thử một email để kiểm tra worker và SMTP:

```bash
docker compose exec api daily-report send-test-email ban@example.com   # hoặc: make test-email to=ban@example.com
```

Khi dev, mọi email đều vào Mailpit (http://localhost:8026), không gửi ra ngoài. Gửi qua SMTP thật thì đặt `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `MAIL_FROM` (xem `.env.example`).

Tài khoản admin tạo (`POST /api/v1/admin/users`) chưa có mật khẩu; worker gửi email có link `FRONTEND_URL/setup-password?token=...` (hết hạn sau 24 giờ, dùng một lần). Chưa có frontend thì mở email trên Mailpit, chép giá trị `token` trên link, gọi `POST /api/v1/auth/setup-password` trên Swagger với body `{"token": "...", "password": "..."}`, rồi đăng nhập bằng email và mật khẩu vừa đặt. Link hết hạn hay email không tới thì admin gửi lại bằng `POST /api/v1/admin/users/{id}/setup-link`.

Worker không tự reload khi sửa code: `docker compose restart worker`. Xem log: `make logs`; mức log của worker (cả log của Celery) lấy từ `LOG_LEVEL`.

## Lưu trữ file

File người dùng tải lên (ảnh đại diện) lưu theo `STORAGE_BACKEND`:

- `local` (mặc định): thư mục `LOCAL_STORAGE_DIR`, API phục vụ tại http://localhost:8001/media/. Trong Docker, file nằm ở volume `media-data`.
- `s3`: đặt `S3_BUCKET` (và `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` nếu cần). Dịch vụ tương thích S3 như MinIO thì đặt thêm `S3_ENDPOINT_URL`.

Đổi backend chỉ cần sửa `.env` (xem `.env.example`) rồi `make dev`, không sửa code.

## Dữ liệu mẫu

```bash
docker compose exec api daily-report seed      # hoặc: make seed (chạy trên máy host)
```

- Tạo 3 bộ phận (DEV, QA, HR), 1 admin, 3 manager, 5 nhân viên và báo cáo 5 ngày làm việc gần nhất.
- Mật khẩu tài khoản mẫu nhập ẩn khi chạy, hoặc đặt qua biến `SEED_USER_PASSWORD`. Không có mật khẩu viết cứng.
- Chỉ thêm phần còn thiếu, chạy lại không tạo trùng. `--reset` xóa toàn bộ dữ liệu rồi seed lại.
- Không chạy được khi `ENVIRONMENT=production`.

| Tài khoản | Role |
| --- | --- |
| `admin@example.com` | ADMIN |
| `manager.dev@example.com`, `manager.qa@example.com`, `manager.hr@example.com` | MANAGER |
| `an.nguyen@example.com`, `binh.tran@example.com`, `cuong.le@example.com`, … | USER |

## Phát triển trên máy host

```bash
make install    # cài dependency, git hook pre-commit
make services   # chỉ chạy postgres, redis, mailpit
make run        # chạy API trên máy host (dừng container api trước: docker compose stop api)
make worker     # chạy Celery worker trên máy host (dừng container worker trước: docker compose stop worker)
```

Celery không hỗ trợ pool mặc định (prefork) trên Windows: chạy worker trên Windows thì dùng `uv run celery -A app.worker worker --pool=solo`, hoặc dùng container `worker`.

## Kiểm tra

```bash
make check      # ruff, mypy strict, pytest + coverage (giống CI)
```

Test chạy trên PostgreSQL thật, database riêng `daily_report_test` (tự tạo nếu chưa có), cần `make services` trước. Mỗi test rollback khi kết thúc.

## Lệnh hay dùng

| Lệnh | Việc |
| --- | --- |
| `make dev` / `make down` | Chạy / dừng toàn bộ stack |
| `make logs` | Xem log API và worker |
| `make admin` | Tạo tài khoản admin (CLI Typer: `uv run daily-report --help`) |
| `make seed` | Tạo dữ liệu mẫu |
| `make test-email to=ban@example.com` | Gửi email thử qua worker, xem trên Mailpit |
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
