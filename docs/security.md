# Rà soát bảo mật

Đối chiếu API với [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/). Mỗi mục ghi kiểm soát đang có, test làm bằng chứng và rủi ro chấp nhận. Rà soát ngày 22/11/2026 (issue #30).

## Phát hiện và cách sửa

| # | Phát hiện | OWASP | Cách sửa |
| --- | --- | --- | --- |
| 1 | FastAPI đọc hết body trước khi kiểm tra token và trước khi endpoint upload kiểm tra dung lượng: JSON vào RAM, file multipart ra file tạm, không giới hạn. Request chưa đăng nhập cũng làm đầy RAM, ổ đĩa được | API4 | `BodySizeLimitMiddleware` (`core/body_limit.py`): body quá 3 MB trả 413 `REQUEST_TOO_LARGE`, không đọc tiếp |
| 2 | Log JSON (production) ghi biến cục bộ của mọi frame khi có exception: mật khẩu, token trong request, JWT secret trong `Settings`. Mặc định của structlog | API8 | Traceback không kèm biến cục bộ, cả log JSON và log console (`core/logging.py`) |
| 3 | CORS bật `allow_credentials` dù API không dùng cookie, cho mọi method, header | API8 | Không gửi kèm credentials; chỉ method, header API dùng; cho frontend đọc `Content-Disposition` (tên file Excel), `Retry-After` (khóa đăng nhập tạm), `X-Request-ID` |
| 4 | Stack dev mở cổng trên mọi interface: Redis không mật khẩu, PostgreSQL, API dùng JWT secret mặc định có trong repo (ai cùng mạng LAN cũng ký được token admin) | API8 | Mọi cổng trong `docker-compose.yml` chỉ mở trên `127.0.0.1` |
| 5 | Test ngoài phạm vi của báo cáo (M3), chi tiết nhân viên (M4), export (M5) lấy "bộ phận khác" là bộ phận chưa có manager. Đột biến bỏ điều kiện manager trong `managed_department_ids` (phạm vi thành "mọi bộ phận có manager"): các test đó vẫn xanh, chỉ ma trận của M1 và test e2e đỏ. Lỗi phạm vi nằm riêng ở một endpoint M3, M4, M5 sẽ lọt | API1 | `tests/api/test_cross_department_access.py`: hai bộ phận, mỗi bên một manager |
| 6 | Chưa có test bảo đảm mọi endpoint cần đăng nhập, đúng role: endpoint mới quên dependency thì không test nào đỏ | API5 | `tests/api/test_access_control.py`: kiểm kê mọi endpoint lấy từ router |
| 7 | Không có gì chặn secret bị commit lên repo công khai | API8 | Hook gitleaks trong `.pre-commit-config.yaml` |

## Checklist

### API1: Phân quyền theo bản ghi (BOLA)

- [x] Phạm vi manager là các bộ phận admin đã gán (bảng `department_managers`), định nghĩa một chỗ: `DepartmentRepository.managed_department_ids`. Mọi truy vấn `/manager` lọc theo phạm vi này; endpoint có `{department_id}` nhận bộ phận qua `ManagedDepartment`; filter `department_id` trên query kiểm tra trong dependency.
- [x] Ngoài phạm vi trả 404 giống id không tồn tại, không lộ bản ghi có thật. Id trên URL giới hạn 1 đến 2^63 − 1 (`IdPath`).
- [x] User chỉ xem báo cáo của mình (`GET /me/reports/{report_id}`), chỉ chọn người nhận trong các manager của bộ phận mình.
- [x] Task nền (email báo cáo mới, thống kê tháng) kiểm tra lại quyền lúc chạy bằng cùng điều kiện với API.
- [x] Ảnh đại diện (`/media`) không cần đăng nhập, key có UUID ngẫu nhiên nên không đoán được; không liệt kê thư mục.
- Bằng chứng: `tests/api/test_department_scope.py` (ma trận quyền mọi endpoint `/manager/departments/{department_id}` và filter `department_id`), `tests/api/test_cross_department_access.py`. Đột biến bỏ điều kiện manager trong `managed_department_ids`: 8/9 test của file sau đỏ (test còn lại là phía user, không dùng phạm vi manager). `test_me_reports.py`: `test_user_cannot_view_report_of_another_user`, `test_create_report_rejects_recipients_outside_own_department`.
- Rủi ro chấp nhận: `DELETE /manager/departments/{department_id}/members/{user_id}` trả 404 khi user không tồn tại, 204 khi user ở bộ phận khác. Manager biết được id nào là user có thật, không đọc được dữ liệu của user đó.

### API2: Xác thực

- [x] Mật khẩu băm Argon2, 8 đến 128 ký tự, có chữ thường, chữ hoa, chữ số và ký tự đặc biệt.
- [x] JWT HS256, secret tối thiểu 32 ký tự; production không chạy với secret mặc định. Chỉ nhận đúng thuật toán đã cấu hình (token `alg: none` bị từ chối), kiểm tra loại token (access, refresh), hạn dùng.
- [x] Access token 15 phút; refresh token 7 ngày, xoay vòng; token đã thu hồi bị gửi lại sau 30 giây ân hạn thì coi là bị lộ, thu hồi mọi phiên của user. Đăng xuất đưa phiên vào blacklist Redis; đổi mật khẩu, khóa, xóa user tăng `token_version`, mọi token cũ hết hiệu lực ngay.
- [x] Đăng nhập sai 5 lần trong 15 phút (theo email) trả 429, đếm cả email không tồn tại. Không có user vẫn băm mật khẩu giả để thời gian phản hồi như nhau.
- [x] Link đặt mật khẩu: token 256 bit, DB lưu SHA-256, dùng một lần, hết hạn sau 24 giờ.
- Bằng chứng: `tests/api/test_auth.py`, `tests/api/test_me.py` (`test_me_rejects_invalid_token`: sai chữ ký, hết hạn, sai loại, `alg-none`), `tests/api/test_setup_password.py`, `tests/api/test_access_control.py` (mọi endpoint ngoài 4 endpoint công khai trả 401 khi thiếu token).
- Rủi ro chấp nhận: khóa tạm theo email nên người khác có thể cố ý khóa một tài khoản 15 phút. Giới hạn theo IP đặt ở reverse proxy.

### API3: Phân quyền theo thuộc tính (BOPLA)

- [x] Schema tạo, sửa bản ghi (user, hồ sơ, bộ phận, manager, thành viên, báo cáo, đặt mật khẩu) có `extra="forbid"`: field lạ trả 422 thay vì bị bỏ qua. `PATCH /me` chỉ sửa họ tên, số điện thoại, ngày sinh; email, role, bộ phận chỉ admin sửa. `RefreshTokenRequest`, `PasswordChange` chỉ nhận token, mật khẩu, không ghi field nào vào bản ghi, nên bỏ qua field lạ.
- [x] Schema trả ra không có `password_hash`, `token_version`, token. Người nhận, người viết đã bị xóa có `is_deleted`, không trả email.
- Bằng chứng: `tests/api/test_me.py::test_update_me_cannot_change_email_or_role`, test schema của từng module.

### API4: Tiêu thụ tài nguyên không giới hạn

- [x] Body của mọi request tối đa 3 MB, kiểm tra trước khi xác thực. Có `Content-Length` thì từ chối trước khi đọc; body gửi từng đoạn thì dừng khi đọc quá 3 MB. Endpoint không đọc body (GET) thì phần body gửi kèm bị bỏ, không vào RAM, ổ đĩa, nên không trả 413.
- [x] File tải lên: ảnh đại diện 2 MB, file Excel 2 MB, giải nén tối đa 10 MB (chặn zip bomb), tối đa 1.000 dòng.
- [x] Phân trang `page_size` tối đa 100, `page` tối đa 1.000.000; mọi chuỗi có `max_length`; danh sách id trong body có giới hạn.
- [x] Timeout kết nối PostgreSQL, Redis, SMTP, S3.
- Bằng chứng: `tests/api/test_body_limit.py`, `tests/api/test_me_avatar.py`, `tests/api/test_admin_user_import.py`, `tests/api/test_list_endpoints.py`.
- Rủi ro chấp nhận: không giới hạn số request theo IP, user (trừ đăng nhập). Đặt ở reverse proxy khi triển khai.

### API5: Phân quyền theo chức năng (BFLA)

- [x] Role kiểm tra một lần ở nhóm router (`/admin`, `/manager`, nhóm báo cáo của role USER), đọc role từ DB ở mỗi request.
- [x] Endpoint công khai chỉ có `GET /health`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/setup-password`.
- Bằng chứng: `tests/api/test_access_control.py` duyệt mọi endpoint của app (đối chiếu Swagger để không sót): endpoint không cần đăng nhập đúng bằng danh sách trên, thiếu token trả 401, role ngoài nhóm trả 403, endpoint ngoài các nhóm role (`/me`, `/auth/logout`) mở cho mọi role (nhóm role mới quên khai tiền tố trong test thì đỏ). Đột biến bỏ dependency role của nhóm `/manager`: `GET /manager/candidates` thành công khai, 24 test đỏ. `tests/api/test_rbac.py` thử cơ chế nhóm.

### API6: Luồng nghiệp vụ nhạy cảm

- [x] Mỗi user một báo cáo một ngày (unique), ngày báo cáo trong 3 ngày gần nhất.
- [x] Email đi qua hàng đợi Celery; thống kê tháng không gửi trùng (`dedup_key`). Gửi lại link đặt mật khẩu chỉ admin làm được.

### API7: SSRF

- [x] API không tải URL do người dùng nhập. Địa chỉ S3, SMTP, frontend chỉ đọc từ cấu hình.

### API8: Cấu hình sai

- [x] Lỗi 500 chỉ trả thông báo chung, chi tiết ở log kèm request-id. 404, 405, 422 theo format chung; 422 không trả lại giá trị đã nhập. Bằng chứng: `tests/unit/test_exceptions.py::test_unexpected_error_hides_internal_details`, `tests/api/test_app.py`.
- [x] Log không ghi biến cục bộ của traceback, không ghi mật khẩu, token. Request-id client gửi chỉ nhận ký tự an toàn. Bằng chứng: `tests/unit/test_logging.py`.
- Rủi ro chấp nhận: lỗi SQL (exception của SQLAlchemy) ghi kèm tham số của câu lệnh để debug: email, nội dung báo cáo; mật khẩu, token chỉ có bản băm. Log đưa ra dịch vụ bên ngoài thì bật `hide_parameters` của engine.
- [x] CORS chỉ cho origin trong `CORS_ORIGINS`, không gửi kèm credentials. Bằng chứng: `tests/unit/test_main.py`.
- [x] FastAPI không bật `debug`. debugpy chỉ có trong image dev; mọi cổng của stack dev chỉ mở trên `127.0.0.1`. Container chạy bằng user không phải root.
- [x] Upload xét loại file bằng nội dung (magic bytes), không tin Content-Type, đuôi file; file lưu với đuôi theo loại thật.
- Quyết định: Swagger (`/docs`) bật ở mọi môi trường. API không có endpoint ẩn, mọi endpoint ngoài 4 endpoint công khai đều cần đăng nhập.
- Để reverse proxy khi triển khai: HTTPS, HSTS, `X-Content-Type-Options: nosniff`.

### API9: Quản lý danh mục API

- [x] Một phiên bản `/api/v1`. Mọi endpoint có trong `docs/api-design.md` và Swagger, không có endpoint debug hay bản cũ. Test kiểm kê đối chiếu Swagger với router.

### API10: Dùng dữ liệu từ nguồn ngoài không an toàn

- [x] File Excel tải lên: chép từng phần sang zip mới (chặn zip bomb), chỉ nhận deflate, stored; giới hạn số dòng; lỗi đọc file đổi thành 415.
- [x] File Excel xuất ra: chữ người dùng nhập không thành công thức, bỏ ký tự XML không hợp lệ.
- [x] Email: Jinja2 autoescape cho template HTML; STARTTLS khi cấu hình SMTP thật.

## Secret

- [x] gitleaks 8.30.1 quét toàn bộ lịch sử (mọi nhánh) và thư mục làm việc ngày 22/11/2026: không có secret.
- [x] Secret chỉ đọc từ biến môi trường qua `Settings`; production không chạy với `JWT_SECRET_KEY` mặc định.
- [x] Giá trị mặc định trong code, `.env.example`, `docker-compose.yml` chỉ dùng cho dev; `.env` không vào git, không vào image Docker.
- [x] Hook gitleaks chạy khi commit (`make install` cài hook; CI chưa chạy gitleaks); ruff bật nhóm luật `S` (bandit), báo mật khẩu ghi cứng.

## Khi thêm endpoint

- Đặt vào đúng nhóm role. Endpoint công khai thì thêm vào `PUBLIC_ENDPOINTS` của `tests/api/test_access_control.py`.
- Dữ liệu theo bộ phận lọc qua `managed_department_ids` hoặc `ManagedDepartment`; endpoint `/manager` trả dữ liệu theo bộ phận thì thêm vào `tests/api/test_cross_department_access.py`.
- Schema tạo, sửa bản ghi có `extra="forbid"`; chuỗi có `max_length`; schema trả ra không có trường nhạy cảm.
- Upload đọc qua `read_upload`, `read_image` với giới hạn riêng nhỏ hơn giới hạn body chung.

## Khi triển khai production

- `ENVIRONMENT=production`, `JWT_SECRET_KEY` ngẫu nhiên (`openssl rand -hex 32`); mật khẩu PostgreSQL, Redis riêng.
- `CORS_ORIGINS` đúng domain của frontend.
- Reverse proxy: HTTPS, HSTS, `X-Content-Type-Options: nosniff`, giới hạn body 3 MB, giới hạn request theo IP cho `/api/v1/auth/*`.
- Không bật `DEBUGPY`.
