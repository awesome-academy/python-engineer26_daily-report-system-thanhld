# Daily Report API

Backend REST API cho hệ thống báo cáo công việc hằng ngày: nhân viên gửi báo cáo, manager theo dõi theo bộ phận, admin quản lý user và bộ phận, hệ thống tự gửi email.

Python 3.13 · FastAPI · PostgreSQL 17 · Redis 7 · SQLAlchemy 2 (async) · Alembic · Celery · Docker Compose.

## Chạy nhanh

Chỉ cần [Docker](https://docs.docker.com/get-docker/) (có Docker Compose v2) và `make`. [uv](https://docs.astral.sh/uv/) chỉ cần khi chạy code, test trên máy host.

```bash
git clone https://github.com/awesome-academy/python-engineer26_daily-report-system-thanhld.git daily-report
cd daily-report
make dev                                                          # build, chạy cả stack, chờ API sẵn sàng
docker compose exec api daily-report seed --password Matkhau@123  # dữ liệu mẫu
```

- Máy không có `make` (Windows): thay `make dev` bằng `docker compose up -d --build`.
- Lần đầu `make dev` mất thêm vài phút để tải image (Python, PostgreSQL, Redis, Mailpit); các lần sau khoảng 20 giây.
- Cổng 8001, 5433, 6380, 8026 đã có chương trình khác dùng: `cp .env.example .env`, sửa các biến `*_PORT`, rồi `make dev` lại.

| Địa chỉ | Dùng để |
| --- | --- |
| http://localhost:8001/docs | Swagger UI, thử API |
| http://localhost:8001/health | Trạng thái API, DB, Redis |
| http://localhost:8026 | Mailpit: xem email hệ thống gửi khi dev |

Migration chạy tự động khi container `api` khởi động. Sửa code trong `src/` thì API tự reload.

Các cổng chỉ mở trên `127.0.0.1` của máy (máy khác cùng mạng không vào được): stack dev dùng JWT secret mặc định có trong repo và Redis không mật khẩu.

## Thử API

Tài khoản mẫu, mật khẩu `Matkhau@123` (giá trị `--password` lúc seed):

| Tài khoản | Role | Gọi được |
| --- | --- | --- |
| `admin@example.com` | ADMIN | `/api/v1/admin/...`: user, bộ phận, gán manager, import Excel |
| `manager.dev@example.com` | MANAGER | `/api/v1/manager/...`: bộ phận DEV, nhân viên, báo cáo, export Excel |
| `an.nguyen@example.com` | USER | `/api/v1/me/reports`: tạo, xem báo cáo của mình |

Mọi role gọi được `/api/v1/auth/...` và `/api/v1/me` (hồ sơ, đổi mật khẩu, ảnh đại diện).

**Swagger:** mở http://localhost:8001/docs, bấm **Authorize**, ô `username` nhập email, ô `password` nhập mật khẩu, rồi gọi endpoint của role đó. Mỗi endpoint có mô tả, ví dụ request, response và ví dụ cho từng mã lỗi (chọn ở ô Examples của phần Responses). Ví dụ dùng id của dữ liệu mẫu (bộ phận DEV id 1, `manager.dev` id 2, `an.nguyen` id 5) khi seed vào DB trống. Ngày trong ví dụ cố định: thử tạo báo cáo thì đổi `report_date` thành hôm nay.

**Postman:** import file [docs/postman/daily-report.postman_collection.json](docs/postman/daily-report.postman_collection.json) (File → Import), rồi chuột phải collection → **Run collection** → **Run**. Collection gọi lần lượt mọi endpoint: đăng nhập ba role, nhân viên tạo báo cáo, admin tạo user và bộ phận, user mới đặt mật khẩu bằng link trong email (đọc từ Mailpit), manager thêm, gỡ thành viên, xem và export báo cáo; cuối cùng xóa dữ liệu vừa tạo nên chạy lại được.

- Gọi từng request: chạy folder **Xác thực** trước. Script lưu token theo role, folder của role nào tự gắn token của role đó.
- Đổi ảnh đại diện, import Excel cần chọn file ở tab Body; chưa chọn file thì hai request này được bỏ qua khi chạy cả collection.
- Đổi cổng hay mật khẩu seed thì sửa biến `baseUrl`, `mailpitUrl`, `password` ở tab Variables của collection.
- Chạy bằng dòng lệnh: `npx newman run docs/postman/daily-report.postman_collection.json`.

## Đăng nhập

Không dùng dữ liệu mẫu thì tạo tài khoản admin đầu tiên:

```bash
docker compose exec api daily-report create-admin   # hoặc: make admin (chạy trên máy host)
```

Mật khẩu tối thiểu 8 ký tự, có chữ thường, chữ hoa, chữ số và ký tự đặc biệt (ví dụ `Matkhau@123`).

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

Email hệ thống gửi: báo cáo mới cho người nhận (S1, sau `POST /api/v1/me/reports`), link đặt mật khẩu (S2, xem dưới), thống kê báo cáo tháng (S3, xem dưới).

Gửi thử một email để kiểm tra worker và SMTP:

```bash
docker compose exec api daily-report send-test-email ban@example.com   # hoặc: make test-email to=ban@example.com
```

Khi dev, mọi email đều vào Mailpit (http://localhost:8026), không gửi ra ngoài. Gửi qua SMTP thật thì đặt `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `MAIL_FROM` (xem `.env.example`).

Tài khoản admin tạo (`POST /api/v1/admin/users`) chưa có mật khẩu; worker gửi email có link `FRONTEND_URL/setup-password?token=...` (hết hạn sau 24 giờ, dùng một lần). Chưa có frontend thì mở email trên Mailpit, chép giá trị `token` trên link, gọi `POST /api/v1/auth/setup-password` trên Swagger với body `{"token": "...", "password": "..."}`, rồi đăng nhập bằng email và mật khẩu vừa đặt. Link hết hạn hay email không tới thì admin gửi lại bằng `POST /api/v1/admin/users/{id}/setup-link`.

**Thống kê tháng (S3):** Celery Beat (container `beat`) đẩy task lúc 08:00 ngày 1 hằng tháng theo giờ Việt Nam, và cùng giờ ngày 2, 3 để gửi bù email còn thiếu (lượt ngày 1 bị lỡ vì Redis lỗi, hay SMTP vẫn lỗi sau 3 lần thử lại). Lượt gửi bù không gửi lại email đã gửi, nên bình thường không gửi gì. Mỗi manager nhận một email cho từng bộ phận mình quản lý: số ngày đã nộp báo cáo so với số ngày làm việc (thứ 2 đến thứ 6, chưa trừ ngày lễ) của từng nhân viên trong tháng trước. Nhân viên mới vào giữa tháng tính từ ngày tạo tài khoản. Email ghi thời điểm tính số liệu: báo cáo bù cho các ngày cuối tháng (được nộp lùi 3 ngày) mà nộp sau 08:00 ngày 1 không có trong thống kê. Mỗi email ghi `dedup_key` vào `email_logs`, nên task chạy lại không gửi trùng. Gửi ngay, không chờ lịch (chỉ tháng đã kết thúc):

```bash
docker compose exec api daily-report send-monthly-summary --month 2026-10   # hoặc: make monthly-summary month=2026-10
```

Bỏ `--month` thì thống kê tháng trước. Manager đã nhận email của tháng đó thì không nhận lại, nên lệnh này cũng dùng để gửi bù khi cả ba lượt theo lịch đều lỡ hoặc lỗi (log `monthly_summary_failed`). Lệnh chỉ đẩy task; số email đã gửi xem ở log worker (`monthly_summary_done sent=... already_sent=...`).

Dữ liệu seed có tài khoản, báo cáo từ ngày đầu tháng trước: chạy lệnh trên (bỏ `--month`) ngay sau khi seed thì mỗi manager nhận một email thống kê tháng trước trên Mailpit.

Worker, beat không tự reload khi sửa code: `docker compose restart worker beat`. Xem log: `make logs`; mức log của worker, beat (cả log của Celery) lấy từ `LOG_LEVEL`.

## Lưu trữ file

File người dùng tải lên (ảnh đại diện) lưu theo `STORAGE_BACKEND`:

- `local` (mặc định): thư mục `LOCAL_STORAGE_DIR`, API phục vụ tại http://localhost:8001/media/. Trong Docker, file nằm ở volume `media-data`.
- `s3`: đặt `S3_BUCKET` (và `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` nếu cần). Dịch vụ tương thích S3 như MinIO thì đặt thêm `S3_ENDPOINT_URL`.

Đổi backend chỉ cần sửa `.env` (xem `.env.example`) rồi `make dev`, không sửa code.

## Dữ liệu mẫu

```bash
docker compose exec api daily-report seed --password Matkhau@123   # hoặc: make seed (chạy trên máy host)
```

- Tạo 3 bộ phận (DEV, QA, HR), 1 admin, 3 manager, 5 nhân viên. Tài khoản mẫu coi như có từ ngày đầu tháng trước; báo cáo mẫu cho các ngày làm việc từ đó đến hôm qua, mỗi nhân viên bỏ trống khoảng 1/5 số ngày (để export, thống kê tháng có người chưa nộp). Không có báo cáo hôm nay, để thử tạo báo cáo.
- Mật khẩu chung của tài khoản mẫu: `--password`, biến `SEED_USER_PASSWORD`, hoặc bỏ trống để nhập ẩn khi chạy. Không có mật khẩu viết cứng.
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

Test chạy trên PostgreSQL thật, database riêng `daily_report_test` (tự tạo nếu chưa có), cần `make services` trước.

| Thư mục | Nội dung |
| --- | --- |
| `tests/unit/` | Hàm thuần, schema, cấu hình |
| `tests/db/` | Service, repository, Celery task, lệnh CLI trên DB thật |
| `tests/api/` | Từng endpoint qua httpx `AsyncClient`, rollback khi kết thúc test |
| `tests/e2e/` | Luồng nghiệp vụ trọn vẹn qua API: commit thật, task đi qua hàng đợi Redis rồi chạy như worker, chỉ thay SMTP bằng hộp thư giả. Xóa sạch dữ liệu sau mỗi test |

Chạy riêng một nhóm: `uv run pytest tests/e2e`.

## Lệnh hay dùng

Mọi lệnh trong `Makefile` (`make help` liệt kê lại). Lệnh dùng `uv run` chạy trên máy host, cần `make install` và `make services` (hoặc `make dev`) trước.

| Lệnh | Việc |
| --- | --- |
| `make dev` / `make down` | Build, chạy / dừng toàn bộ stack Docker |
| `make debug` | Chạy stack với API dưới debugpy (mục Debug) |
| `make logs` | Xem log API, worker, beat |
| `make install` | Cài dependency, git hook pre-commit (máy host) |
| `make services` | Chỉ chạy PostgreSQL, Redis, Mailpit |
| `make run` / `make worker` | Chạy API / Celery worker trên máy host |
| `make admin` | Tạo tài khoản admin |
| `make seed` | Tạo dữ liệu mẫu |
| `make test-email to=ban@example.com` | Gửi email thử qua worker, xem trên Mailpit |
| `make monthly-summary month=2026-10` | Gửi email thống kê tháng ngay, không chờ Celery Beat |
| `make migrate` | Chạy migration tới bản mới nhất |
| `make migration m="add users table"` | Tạo migration từ model |
| `make lint` / `make format` | Kiểm tra / tự sửa lint, format (ruff) |
| `make typecheck` | Kiểm tra kiểu (mypy strict) |
| `make test` | Chạy test kèm coverage |
| `make check` | `lint`, `typecheck`, `test` như CI |
| `make help` | Liệt kê mọi lệnh |

Lệnh quản trị (CLI Typer) chạy trong container bằng `docker compose exec api daily-report <lệnh>`, hoặc trên máy host bằng `uv run daily-report <lệnh>`. Thêm `--help` sau tên lệnh để xem đủ tham số.

| Lệnh | Việc |
| --- | --- |
| `create-admin [--email ... --full-name ... --password ...]` | Tạo tài khoản admin; thiếu tham số thì hỏi, mật khẩu nhập ẩn (hoặc biến `ADMIN_PASSWORD`) |
| `seed [--password ...] [--reset [-y]]` | Tạo dữ liệu mẫu; `--reset` xóa toàn bộ dữ liệu trước |
| `send-test-email <email>` | Gửi email thử qua worker |
| `send-monthly-summary [--month YYYY-MM]` | Gửi email thống kê tháng (mặc định tháng trước) |

## Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `make dev` báo `port is already allocated`, `address already in use` | Cổng đã có chương trình khác dùng: `cp .env.example .env`, đổi `API_PORT`, `POSTGRES_PORT`… rồi `make dev`. Đổi `API_PORT` thì đổi cả `LOCAL_STORAGE_BASE_URL`, và `baseUrl` trong Postman |
| Seed, đăng nhập lỗi `relation ... does not exist` | Migration chưa chạy xong hoặc lỗi: `docker compose logs api` |
| Đăng nhập trả 401 `INVALID_CREDENTIALS` với tài khoản mẫu | Mật khẩu là giá trị `--password` lúc seed lần đầu; seed lại không đổi mật khẩu tài khoản đã có. Đặt lại: `docker compose exec api daily-report seed --reset -y --password Matkhau@123` (xóa toàn bộ dữ liệu) |
| Đăng nhập trả 429 `TOO_MANY_ATTEMPTS` | Sai mật khẩu quá 5 lần: chờ hết thời gian trong `Retry-After` (tối đa 15 phút) |
| Email không tới Mailpit | Worker chưa chạy hoặc lỗi: `make logs`, sửa code thì `docker compose restart worker beat` |

## Tài liệu

| File | Nội dung |
| --- | --- |
| [docs/requirements.md](docs/requirements.md) | 15 chức năng, endpoint, kỹ thuật, câu hỏi cần PM chốt |
| [docs/architecture.md](docs/architecture.md) | Công nghệ, kiến trúc, cấu trúc thư mục, quyết định kỹ thuật |
| [docs/database.md](docs/database.md) | ERD, bảng, ràng buộc, index |
| [docs/api-design.md](docs/api-design.md) | Quy ước API, mã lỗi, 41 endpoint, Swagger và Postman |
| [docs/postman/](docs/postman/) | Postman collection gọi mọi endpoint |
| [docs/security.md](docs/security.md) | Rà soát bảo mật theo OWASP API Top 10, checklist khi thêm endpoint, khi triển khai |
| [docs/progress/](docs/progress/) | Kế hoạch 10 ngày, báo cáo từng ngày |
