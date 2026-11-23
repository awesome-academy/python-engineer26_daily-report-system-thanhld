# Kịch bản demo

Demo 60 phút: 45 phút demo, 15 phút hỏi đáp, 10 cảnh. Công cụ: Swagger UI, Mailpit, terminal, VS Code. Phạm vi: đủ 15 chức năng (U1–U3, M1–M5, A1–A4, S1–S3), logging và debug.

Buổi demo chỉ có 1 tiếng: mọi dữ liệu, id, file phải chuẩn bị xong trước giờ demo theo mục "Chuẩn bị dữ liệu". Trong buổi chỉ gọi API và chạy các lệnh đã ghi sẵn, không dựng môi trường, không đi tìm id.

Kịch bản đã chạy thử trọn vẹn trên stack Docker (`make debug`) với dữ liệu `seed --reset`: mã HTTP, mã lỗi, tiêu đề email, nội dung file Excel, dòng log, điểm dừng của debugger ghi dưới đây là kết quả thật. Id trong kịch bản đúng khi seed bằng `--reset` (id bắt đầu lại từ 1).

## Điều kiện bắt buộc

**Code:** mọi pull request đã merge vào `master`, CI xanh. Demo trên bản clone sạch của `master`:

```bash
git fetch origin && git checkout master && git pull
git log --oneline -1   # commit merge mới nhất của master
```

**Tổng duyệt đủ 45 phút, có bấm giờ:** làm hết mục "Dựng môi trường" và "Chuẩn bị dữ liệu", rồi đi hết các cảnh theo lịch trình. Cảnh nào lố giờ thì cắt theo dòng "Thiếu giờ" ở cuối cảnh. Tổng duyệt xong thì `seed --reset` lại, vì nhiều bước chỉ chạy được một lần (báo cáo hôm nay, tài khoản eve, bộ phận BA, import, đổi mật khẩu, khóa giang).

## Dựng môi trường

Làm một lần, trước buổi demo. Stack chạy bằng Docker Compose: API, Celery worker, Celery Beat, PostgreSQL 17, Redis 7, Mailpit. Container `api` tự chạy `alembic upgrade head` khi khởi động. Không cần file `.env`: giá trị mặc định đủ cho demo.

Chạy cả buổi bằng `make debug` thay cho `make dev`: API chạy dưới debugpy (cổng 5678, chỉ mở trên 127.0.0.1), tới cảnh 9 chỉ cần attach VS Code, không phải khởi động lại giữa buổi.

```bash
make debug
docker compose ps                       # api healthy; worker, beat, postgres, redis, mailpit chạy
curl http://localhost:8001/health       # "status": "ok"
```

Reset hẳn dữ liệu (xóa volume PostgreSQL, Redis, ảnh đại diện): `docker compose down -v`, rồi `make debug` và làm lại mục "Chuẩn bị dữ liệu".

## Chuẩn bị dữ liệu

Sáng ngày demo, xong trước giờ demo ít nhất 30 phút.

**1. Seed lại theo ngày demo** (khoảng 2 phút):

```bash
docker compose exec api daily-report seed --reset -y --password Matkhau@123
```

Tài khoản mẫu có từ ngày đầu tháng trước, báo cáo các ngày làm việc từ đó đến hôm qua (mỗi nhân viên bỏ trống khoảng 1/5 số ngày), chưa ai có báo cáo hôm nay. Seed từ hôm trước thì cảnh 3 nhận 409 vì báo cáo "hôm nay" đã tạo lúc tổng duyệt, và cảnh 8 không gửi email nào vì thống kê tháng đã gửi.

**2. File demo** có sẵn trong repo ở [`docs/demo-files/`](demo-files/): `avatar.png` (cảnh 2), `import-loi.xlsx`, `import-dung.xlsx`, `khong-phai-excel.txt` (cảnh 7). Không cần tự làm file.

**3. Kiểm tra cuối, 15 phút trước giờ demo:**

- [ ] `docker compose ps`: `api` healthy; `worker`, `beat`, `postgres`, `redis`, `mailpit` đang chạy; cột cổng của `api` có `127.0.0.1:5678`.
- [ ] Mailpit (http://localhost:8026): xóa hết thư (nút Delete all).
- [ ] Mở 4 tab Swagger (http://localhost:8001/docs), mỗi tab bấm **Authorize** một tài khoản: `an.nguyen`, `giang.vo`, `manager.dev`, `admin` (đều `@example.com`, mật khẩu `Matkhau@123`). Đổi vai bằng cách đổi tab.
- [ ] Hai terminal ở thư mục repo: một chạy `docker compose logs -f api worker`, một để gõ lệnh.
- [ ] VS Code mở repo, đặt sẵn breakpoint ở `src/app/modules/reports/service.py` dòng 50 (`return await self.reports.search_by_author(...)` trong `ReportService.list_my_reports`).
- [ ] Mở sẵn trang Actions của repo, một lần chạy CI xanh (cảnh 10).
- [ ] Có sẵn video quay buổi tổng duyệt, phòng khi môi trường hỏng.

Access token hết hạn sau 15 phút. Swagger báo 401 giữa buổi thì bấm **Authorize** → **Logout** → đăng nhập lại, mất vài giây.

## Tài khoản và id

Do lệnh seed tạo ra. Mọi tài khoản dùng mật khẩu `Matkhau@123`.

| Id | Tài khoản (`@example.com`) | Role | Bộ phận | Vai trong demo |
| --- | --- | --- | --- | --- |
| 1 | `admin` | ADMIN | — | Quản lý tài khoản, bộ phận, import |
| 2 | `manager.dev` | MANAGER | DEV (id 1) | Manager chính: xem báo cáo, thêm nhân viên, export |
| 3 | `manager.qa` | MANAGER | QA (id 2) | Người nhận không hợp lệ của An |
| 4 | `manager.hr` | MANAGER | HR (id 3) | |
| 5 | `an.nguyen` | USER | DEV | Nhân viên chính: hồ sơ, báo cáo; dùng ở cảnh debug |
| 6 | `binh.tran` | USER | DEV | "Chưa nộp" trong file export |
| 7 | `cuong.le` | USER | QA | Ngoài phạm vi của manager.dev |
| 8 | `dung.pham` | USER | QA | |
| 9 | `giang.vo` | USER | HR | Đổi mật khẩu (cảnh 2), bị khóa (cảnh 5) |

Tạo trong buổi demo: tài khoản `eve.tran` (id 10) và bộ phận BA (id 4) ở cảnh 5, hai tài khoản import (id 11, 12) ở cảnh 7.

## Lịch trình 60 phút

| Bắt đầu | Phút | Cảnh | Vai | Ý cần người xem nhớ |
| --- | --- | --- | --- | --- |
| 00:00 | 3 | 1. Giới thiệu và kiến trúc | — | Bài toán, kiến trúc, phạm vi |
| 03:00 | 6 | 2. Đăng nhập và hồ sơ (U1, U2) | an, giang | Refresh token dùng một lần; không tự nâng quyền; đổi mật khẩu thu hồi phiên cũ |
| 09:00 | 7 | 3. Nhân viên nộp báo cáo (U3, S1) | an | Quy tắc ngày, người nhận, mỗi ngày một báo cáo, email qua worker |
| 16:00 | 4 | 4. Manager theo dõi bộ phận (M1, M3, M4) | manager.dev, an | Chỉ thấy bộ phận mình quản lý; ngoài phạm vi là 404 |
| 20:00 | 8 | 5. Admin: tài khoản và bộ phận (A1, A2, A3, S2, M2) | admin, manager.dev | Tài khoản mới tự đặt mật khẩu; manager tự thêm nhân viên; bảo vệ admin, manager |
| 28:00 | 3 | 6. Export Excel (M5) | manager.dev | Một dòng mỗi nhân viên, chưa nộp tô đỏ, chữ không thành công thức |
| 31:00 | 3 | 7. Import nhân viên (A4) | admin | File có lỗi thì không tạo ai, lỗi báo theo dòng |
| 34:00 | 4 | 8. Thống kê tháng và CLI (S3) | terminal, Mailpit | Celery Beat; chạy lại không gửi trùng |
| 38:00 | 4 | 9. Logging và debug | an, terminal, VS Code | Request ID xuyên suốt log; debugpy trong Docker |
| 42:00 | 3 | 10. Chất lượng và tiến độ | — | Test, CI, việc còn lại |
| 45:00 | 15 | Hỏi đáp | — | |

Đường dẫn trong các cảnh tính từ `/api/v1`. Cột "Tab" là tab Swagger (vai) dùng để gọi.

## 1. Giới thiệu và kiến trúc (00:00–03:00)

Mục tiêu: người xem hiểu hệ thống làm gì và các thành phần nói chuyện với nhau thế nào.

Nói gì:

- Bài toán: nhân viên gửi báo cáo công việc hằng ngày cho manager bộ phận; manager theo dõi, export; admin quản lý tài khoản, bộ phận, import; hệ thống tự gửi email (báo cáo mới, link đặt mật khẩu, thống kê tháng).
- Kiến trúc (`docs/architecture.md`): FastAPI + SQLAlchemy async trên PostgreSQL; Redis giữ trạng thái phiên, khóa tạm và làm hàng đợi cho Celery; worker gửi email qua SMTP (Mailpit khi dev); Celery Beat chạy lịch thống kê tháng. Modular monolith: mỗi module router → service → repository; mọi lỗi cùng một dạng `{"error": {"code", "message", "details"}}`.
- API nhóm theo vai: `/auth`, `/me`, `/manager`, `/admin`, 41 endpoint. Mở `/docs`: endpoint có mô tả, ví dụ request, response, ví dụ cho từng mã lỗi.

## 2. Đăng nhập và hồ sơ (U1, U2, 03:00–09:00)

Mục tiêu: cơ chế token và các thao tác tự phục vụ của người dùng.

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| an | `POST /auth/login` (Try it out) | `username` `an.nguyen@example.com`, `password` `Matkhau@123` | 200, `access_token`, `refresh_token`, `expires_in` 900 |
| an | `POST /auth/refresh` | `{"refresh_token": "<token vừa nhận>"}` | 200, cặp token mới |
| an | `POST /auth/refresh` | Gửi lại đúng refresh token cũ, trong 30 giây sau bước trên | 401 `UNAUTHORIZED` |
| an | `GET /me` | | 200, `role` USER, `department` DEV |
| an | `PATCH /me` | `{"role": "ADMIN"}` | 422 `VALIDATION_ERROR`, field `body.role` |
| an | `PUT /me/avatar` | `docs/demo-files/avatar.png` | 200, `avatar_url`; mở link thấy ảnh |
| giang | `PUT /me/password` | `{"current_password": "Matkhau@123", "new_password": "Moi@12345"}` | 200, cặp token mới |
| giang | `GET /me` | Token cũ của tab | 401; **Authorize** lại bằng mật khẩu `Moi@12345` |

Nói gì:

- Refresh token xoay vòng, mỗi token dùng một lần. Gửi lại token cũ trong 30 giây (client timeout rồi gửi lại) chỉ bị từ chối; sau 30 giây bị coi là token bị lộ: mọi phiên của tài khoản bị thu hồi.
- Sai mật khẩu 5 lần thì khóa tạm 15 phút (429, header `Retry-After`), đếm theo email kể cả email không tồn tại, nên không dò được email nào có thật. Đăng xuất thu hồi cả phiên ngay: refresh token trong DB, access token qua blacklist Redis.
- Sửa hồ sơ từng phần; field không được sửa (email, role) hay field lạ trả 422, không bỏ qua âm thầm. Loại ảnh xét theo nội dung file (magic bytes), không theo đuôi: file text đổi đuôi `.png` trả 415. Ảnh lưu local hoặc S3, đổi bằng cấu hình.
- Đổi mật khẩu tăng `token_version`: mọi phiên khác hết hiệu lực ngay, phiên hiện tại nhận token mới.

Thiếu giờ: bỏ bước `PATCH /me`, bước ảnh đại diện.

## 3. Nhân viên nộp báo cáo (U3, S1, 09:00–16:00)

Mục tiêu: luồng nghiệp vụ chính và email gửi bất đồng bộ.

Body tạo báo cáo (thay `<hôm nay>` bằng ngày demo, dạng `2026-11-23`). `planned_work` cố ý bắt đầu bằng `=` để cảnh 6 chứng minh file Excel không chạy công thức:

```json
{
  "report_date": "<hôm nay>",
  "planned_work": "=SUM(1,2) Hoàn thành API xuất báo cáo Excel",
  "actual_work": "Xong API, còn test ngày nghỉ",
  "incomplete_reason": "Chờ chốt danh sách ngày nghỉ",
  "next_day_plan": "Viết test ngày nghỉ, demo"
}
```

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| an | `GET /me/recipients` | | 200, chỉ `manager.dev` |
| an | `POST /me/reports` | Body trên, thêm `"recipient_ids": [3]` (manager.qa) | 422 `INVALID_RECIPIENT`, `invalid_ids` [3] |
| an | `POST /me/reports` | Body trên | 201, `recipients` là manager.dev |
| Mailpit | | | Email "[Daily Report API] Báo cáo ngày dd/mm/yyyy của Nguyễn Văn An" tới manager.dev |
| an | `POST /me/reports` | Gửi lại body trên | 409 `REPORT_ALREADY_EXISTS` |
| an | `POST /me/reports` | `report_date` 4 ngày trước | 422 `REPORT_DATE_OUT_OF_RANGE`, `details` có `min_date` (hôm nay − 3), `max_date` (hôm nay) |
| an | `POST /me/reports` | `report_date` hôm qua, `"actual_work": "   "` (toàn dấu cách) | 422 `VALIDATION_ERROR`, field `body.actual_work`: cắt khoảng trắng thành rỗng |
| an | `GET /me/reports` | | 200, báo cáo vừa tạo đứng đầu, có `meta.total` |

Nói gì:

- Người nhận là manager của bộ phận mình (Q4), không gửi `recipient_ids` là gửi tất cả. Báo cáo được lùi tối đa 3 ngày (Q6), không cho ngày tương lai, không trước ngày tạo tài khoản; đã gửi thì không sửa, xóa (Q5). Chỉ role USER viết báo cáo (Q3): manager, admin gọi trả 403.
- Mỗi người một báo cáo mỗi ngày nhờ unique index: hai request cùng lúc cũng chỉ một request thành công, request kia nhận 409 chứ không phải 500.
- Báo cáo và người nhận lưu trong một transaction; commit xong mới đẩy task email vào Redis. Redis lỗi thì báo cáo vẫn lưu, API vẫn trả 201; SMTP lỗi thì worker thử lại tối đa 3 lần.
- Báo cáo của người khác trả 404, không phải 403: không dò được id nào tồn tại.

Thiếu giờ: bỏ bước người nhận ngoài bộ phận, bước toàn dấu cách.

## 4. Manager theo dõi bộ phận (M1, M3, M4, 16:00–20:00)

Mục tiêu: manager chỉ thấy dữ liệu của bộ phận mình quản lý.

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| manager.dev | `GET /manager/departments` | | 200, chỉ DEV |
| manager.dev | `GET /manager/reports` | `keyword` `nguyen` | 200, báo cáo của Nguyễn Văn An (tìm không dấu), có phân trang |
| manager.dev | `GET /manager/reports/{id}` | Id báo cáo An vừa tạo | 200, bộ phận lúc viết (DEV), người nhận |
| manager.dev | `GET /manager/employees/7` | cuong.le (QA) | 404 `NOT_FOUND` |
| an | `GET /manager/reports` | Nhân viên gọi danh sách của manager | 403 `FORBIDDEN` |

Nói gì:

- Phạm vi là bộ phận admin gán cho manager, một chỗ định nghĩa (`ManagedDepartment`), áp dụng cho mọi endpoint `/manager`. Ngoài phạm vi (bộ phận khác như `GET /manager/departments/2`, nhân viên, báo cáo của bộ phận khác) trả 404 giống không tồn tại; sai role cho cả nhóm endpoint thì 403.
- Báo cáo thuộc bộ phận lúc viết: nhân viên chuyển bộ phận thì báo cáo cũ vẫn ở bộ phận cũ.
- Danh sách đều phân trang; số câu SQL không đổi theo số dòng (có test đếm câu SQL); index `(department_id, report_date)`.

Thiếu giờ: bỏ bước tab an.

## 5. Admin: tài khoản và bộ phận (A1, A2, A3, S2, M2, 20:00–28:00)

Mục tiêu: vòng đời tài khoản, cơ cấu bộ phận và các quy tắc bảo vệ dữ liệu.

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `POST /admin/users` | `{"email": "eve.tran@example.com", "full_name": "Trần Thị Eve", "role": "USER"}` | 201, id 10; không nhận mật khẩu |
| Mailpit | | | Email "[Daily Report API] Đặt mật khẩu cho tài khoản của bạn" tới eve; chép giá trị `token` trên link |
| admin | `POST /auth/setup-password` | `{"token": "<token>", "password": "Eve@12345"}` | 204; eve đăng nhập được bằng mật khẩu này |
| admin | `POST /admin/departments` | `{"code": "ba", "name": "Phân tích nghiệp vụ"}` | 201, id 4, `code` lưu là `BA` |
| admin | `POST /admin/departments/4/managers` | `{"user_id": 2}` | 200; manager.dev giờ quản lý DEV và BA |
| manager.dev | `POST /manager/departments/4/members` | `{"user_ids": [10]}` (eve, chưa thuộc bộ phận nào) | 204 |
| admin | `PATCH /admin/users/2` | `{"role": "USER"}` (manager.dev đang quản lý DEV, BA) | 409 `USER_MANAGES_DEPARTMENTS` |
| admin | `PATCH /admin/users/9` | `{"is_active": false}` (khóa giang) | 200; tab giang `GET /me` trả 401 ngay |
| admin | `PATCH /admin/users/1` | `{"is_active": false}` (admin tự khóa) | 400 `CANNOT_MODIFY_OWN_ACCOUNT` |

Nói gì:

- Admin không đặt mật khẩu hộ (Q8): user nhận link dùng một lần (dùng lại trả 400), hết hạn 24 giờ, token chỉ lưu dạng băm. Link hết hạn thì admin gửi lại (`POST /admin/users/{id}/setup-link`). Email không phân biệt hoa thường: tạo lại `EVE.TRAN@example.com` trả 409.
- Mã bộ phận duy nhất, không phân biệt hoa thường (tạo lại `BA` trả 409). Chỉ role MANAGER được gán quản lý (gán an trả 422). Một bộ phận nhiều manager, một manager nhiều bộ phận (Q2).
- Manager chỉ thêm được USER chưa thuộc bộ phận nào (danh sách ở `GET /manager/candidates`; thêm cuong.le đang ở QA trả 422); thêm lại người đã thêm không lỗi, nên client gửi lại khi timeout vẫn an toàn.
- Xóa user, bộ phận là xóa mềm, giữ lịch sử (Q9); bộ phận còn thành viên thì không xóa được (xóa BA lúc này trả 409). Khóa, xóa, đổi role có hiệu lực ngay ở request kế tiếp. Luôn còn ít nhất một admin đăng nhập được; manager đang quản lý bộ phận phải được gỡ trước khi hạ role, khóa, xóa.

Thiếu giờ: bỏ bước hạ role manager.dev, bước admin tự khóa.

## 6. Export Excel (M5, 28:00–31:00)

Mục tiêu: manager lấy được file báo cáo theo ngày để gửi lên trên.

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| manager.dev | `GET /manager/reports/export` | Bỏ trống `date` (hôm nay); bấm "Download file", mở bằng Excel | 200, file `bao-cao-<hôm nay>.xlsx`, 10 cột: BA Eve "Chưa nộp", DEV An "Đã nộp", Bình "Chưa nộp" (ô đỏ); ô "Công việc dự định" của An hiện nguyên văn `=SUM(1,2) …`, không thành công thức |
| manager.dev | `GET /manager/reports/export` | `date` là ngày làm việc trước | 200, file của ngày đó; dữ liệu mẫu có người bỏ trống ngày đó |
| manager.dev | `GET /manager/reports/export` | `date` ngày mai | 422 `REPORT_DATE_OUT_OF_RANGE`, `details.max_date` hôm nay |
| manager.dev | `GET /manager/reports/export` | `department_id` 2 (QA) | 404 `NOT_FOUND` |

Nói gì:

- Mỗi nhân viên của bộ phận một dòng, sắp theo mã bộ phận rồi họ tên; đã nộp kèm 4 nội dung và giờ gửi theo giờ Việt Nam.
- Đọc dữ liệu một ngày bằng một câu SQL, commit để trả kết nối DB, ghi bằng openpyxl write-only rồi mới gửi dạng stream từng đoạn 64 KB.
- Nội dung người dùng nhập luôn ghi thành ô chữ, không thành công thức Excel (chống Excel injection).

Thiếu giờ: bỏ bước ngày làm việc trước, bước `department_id` 2.

## 7. Import nhân viên (A4, 31:00–34:00)

Mục tiêu: nhập hàng loạt an toàn, lỗi báo rõ dòng và cột.

Hai file import trong `docs/demo-files/`, làm từ file mẫu `GET /admin/users/import-template`:

| File | Email | Họ tên | Số điện thoại | Ngày sinh | Mã bộ phận | Role |
| --- | --- | --- | --- | --- | --- | --- |
| `import-loi.xlsx` | hoa.nguyen@example.com | Nguyễn Thị Hoa | 0901234567 | 15/03/1999 | DEV | USER |
| | an.nguyen@example.com | Trùng email | | | DEV | |
| | khoa.le@example.com | Lê Văn Khoa | | | XYZ | USER |
| `import-dung.xlsx` | hoa.nguyen@example.com | Nguyễn Thị Hoa | 0901234567 | 15/03/1999 | DEV | USER |
| | khoa.le@example.com | Lê Văn Khoa | | | QA | USER |

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `GET /admin/users/import-template` | | 200, file mẫu: dòng tiêu đề và sheet hướng dẫn |
| admin | `POST /admin/users/import` | `import-loi.xlsx` | 422 `IMPORT_VALIDATION_FAILED`: dòng 3 `email` đã dùng, dòng 4 `department_code` không có; không tạo ai |
| admin | `POST /admin/users/import` | `import-dung.xlsx` | 201, `created_count` 2; Mailpit có email đặt mật khẩu tới hoa.nguyen, khoa.le |
| admin | `POST /admin/users/import` | `khong-phai-excel.txt` | 415 `UNSUPPORTED_FILE_TYPE` |

Nói gì: kiểm tra cả file rồi mới ghi trong một transaction, trả mọi lỗi theo dòng một lần, nên sửa file rồi import lại không bị tạo trùng; cùng quy tắc với `POST /admin/users`; tối đa 2 MB, 1.000 dòng; chặn file zip giải nén quá lớn; email đặt mật khẩu chỉ gửi sau khi commit.

Thiếu giờ: bỏ bước file mẫu, bước file text.

## 8. Thống kê tháng và CLI (S3, 34:00–38:00)

Mục tiêu: job cuối tháng gửi đúng một lần cho mỗi bộ phận, gửi bù được khi lỗi.

| Ở đâu | Lệnh, thao tác | Kết quả |
| --- | --- | --- |
| VS Code | `src/app/worker.py`, `beat_schedule` | Task chạy 08:00 ngày 1 hằng tháng (giờ Việt Nam), chạy lại ngày 2, 3 để gửi bù. Hôm nay không phải ngày 1 nên demo bằng CLI |
| Terminal | `docker compose exec api daily-report send-monthly-summary` | Mailpit: 3 email "[Daily Report API] Thống kê báo cáo tháng MM/YYYY của bộ phận ..." (tháng trước), mỗi bộ phận một email gửi manager của bộ phận đó; mở một email xem bảng từng nhân viên |
| Terminal | Chạy lại lệnh trên | Không có email mới; terminal log: dòng `monthly_summary_done` có `already_sent=3`, `sent=0` |

Nói gì:

- Mỗi email giữ `dedup_key` (tháng, bộ phận, người nhận) trong `email_logs`, ghi bằng `INSERT ... ON CONFLICT DO NOTHING` cùng transaction với lần gửi: job chạy lại, hay CLI chạy cùng lúc với job, cũng không gửi trùng.
- Số liệu là một câu SQL GROUP BY bộ phận, nhân viên: số ngày đã nộp trên số ngày làm việc (thứ 2 đến thứ 6, chưa trừ ngày lễ, Q12); nhân viên mới tính từ ngày tạo tài khoản.
- SMTP lỗi thì worker thử lại; hết lượt ghi `FAILED`, lượt ngày 2, 3 gửi bù. Gửi tháng khác: `make monthly-summary month=2026-10`.

Thiếu giờ: bỏ lần chạy lại, chỉ nói "chạy lại thì `already_sent=3`".

## 9. Logging và debug (38:00–42:00)

Mục tiêu: phần vận hành chạy được thật: tra log theo request, debug code đang chạy trong Docker.

| Ở đâu | Lệnh, thao tác | Kết quả |
| --- | --- | --- |
| an | `GET /me/reports` | 200; response header có `x-request-id` (32 ký tự hex) |
| Terminal | `docker compose logs api \| grep <request_id>` | Đúng một dòng `request` có `method=GET path=/api/v1/me/reports status=200 duration_ms=...`, không có body, mật khẩu, token |
| VS Code | Run and Debug → "Docker: attach API (debugpy)" | Thanh debug hiện, breakpoint ở `service.py` dòng 50 được xác nhận |
| an | `GET /me/reports` | Request dừng ở breakpoint trong `ReportService.list_my_reports`: xem biến `params` (`page=1, page_size=20`), `author`; bấm Continue thì Swagger nhận 200 |

Nói gì:

- Mỗi request một request ID (lấy từ header `X-Request-ID` của client nếu hợp lệ, không thì tự sinh), gắn vào mọi dòng log trong request và trả lại trong header: người dùng báo lỗi kèm ID là tìm được đúng dòng log. Production ghi log JSON (`ENVIRONMENT=production`).
- Log chỉ ghi method, path, status, thời gian; không ghi body, mật khẩu, token.
- debugpy chỉ chạy khi `DEBUGPY=1` (`make debug`), cổng 5678 chỉ mở trên 127.0.0.1; chế độ debug không dùng `--reload` để breakpoint không mất khi code reload. Cấu hình attach ở `.vscode/launch.json`.

Thiếu giờ: bỏ phần debug, chỉ mở `.vscode/launch.json` và lệnh `make debug` trong Makefile.

## 10. Chất lượng và tiến độ (42:00–45:00)

**Chất lượng:**

- Hơn 1.200 test chạy trên PostgreSQL, Redis thật (unit, DB, API, e2e), coverage trên 99%. Có test riêng cho ma trận quyền theo bộ phận, kiểm kê phân quyền mọi endpoint lấy từ route thật, số câu SQL của mọi danh sách, hai transaction chạy đồng thời, mốc giờ theo giờ Việt Nam.
- Chỉ vào trang Actions đã mở sẵn: mỗi PR chạy ruff, mypy strict, pytest trên PostgreSQL thật; coverage dưới 80% thì đỏ.
- UAT ngày 22/11: đi hết các luồng theo vai, Postman collection (`docs/postman/`) gọi mọi endpoint, gửi dữ liệu lạ tới mọi endpoint; 3 lỗi tìm thấy đã sửa.

**Tiến độ:** đã xong 15/15 chức năng; việc còn lại, giới hạn đã biết ở `docs/progress/handover.md`.

## Hỏi đáp: câu hỏi có thể gặp

**Hai request tạo báo cáo cùng lúc thì sao?** Unique `(author_id, report_date)` trong DB: một request thành công, request kia nhận 409, không phải 500. Các chỗ ghi đồng thời khác (gán manager, thêm thành viên, khóa admin cuối cùng) khóa dòng theo thứ tự cố định, có test chạy hai transaction thật.

**Manager gọi id ngoài phạm vi sao trả 404 chứ không phải 403?** Để không dò được id nào là bộ phận, nhân viên, báo cáo có thật. Thứ tự lỗi cố định: 401 → 403 (sai role) → 422 tham số URL → 404 phạm vi → 422 body.

**Đổi role, khóa tài khoản có hiệu lực ngay không?** Có. Role đọc từ DB ở mỗi request; khóa, xóa, đổi mật khẩu tăng `token_version` nên token cũ bị từ chối ở request kế tiếp.

**Redis hoặc SMTP lỗi thì sao?** Tạo báo cáo, tạo user vẫn thành công (201), lỗi đẩy task chỉ ghi log. SMTP lỗi thì worker thử lại 3 lần (30s, 60s, 120s), hết lượt ghi `email_logs` `FAILED`. `/health` trả 503 khi DB hoặc Redis lỗi.

**Vì sao báo cáo lưu `department_id` riêng?** Giữ lịch sử: nhân viên chuyển bộ phận thì báo cáo cũ vẫn thuộc bộ phận cũ, manager cũ vẫn xem được.

**Export, import dữ liệu lớn có tràn RAM không?** Export đọc một ngày bằng một câu SQL, openpyxl write-only không giữ cả sheet, file gửi dạng stream. Import giới hạn 2 MB, 1.000 dòng, chặn file zip giải nén quá lớn.

**Hiệu năng khi dữ liệu lớn?** Test đếm câu SQL cho mọi danh sách; danh sách báo cáo của manager đọc index `(department_id, report_date) INCLUDE (author_id, id)`. Số đo `EXPLAIN ANALYZE` trên 2,47 triệu báo cáo ở `docs/database.md`.

**Bảo mật?** Checklist theo OWASP API Security Top 10 ([security.md](security.md)): phân quyền mọi endpoint có test duyệt route thật, giới hạn dung lượng body, log không ghi mật khẩu, token, cổng dev và debug chỉ mở trên 127.0.0.1. Dữ liệu lạ (ký tự NUL, số quá lớn, file giả) trả 4xx, không trả 500.

**Chưa làm gì?** Sửa báo cáo, quên mật khẩu, frontend, deploy thật nằm ngoài phạm vi (`docs/requirements.md` mục 3). Ngày lễ chưa trừ trong thống kê, chưa lưu lịch sử thành viên bộ phận. Danh sách đầy đủ ở `docs/progress/handover.md`.

## Khi có sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| Swagger báo 401 giữa buổi | Access token hết hạn (15 phút), hoặc phiên bị thu hồi (gửi lại refresh token cũ sau 30 giây, đổi mật khẩu, bị khóa) | **Authorize** → **Logout** → đăng nhập lại |
| Đăng nhập trả 429 | Sai mật khẩu 5 lần với email đó | Chờ theo `Retry-After` (tối đa 15 phút) hoặc dùng tài khoản khác |
| Tạo báo cáo hôm nay trả 409 ngay lần đầu | Đã tạo lúc tổng duyệt | `seed --reset` (mục Chuẩn bị dữ liệu), hoặc dùng `binh.tran` |
| Thống kê tháng không gửi email nào, log `already_sent=3` ngay lần đầu | Đã chạy lúc tổng duyệt | `seed --reset`, hoặc chỉ nói về lần chạy lại |
| Đăng nhập trả 401 với tài khoản mẫu | Seed lần đầu bằng mật khẩu khác | `seed --reset -y --password Matkhau@123` |
| Không thấy email trên Mailpit | Worker chưa chạy hoặc mất kết nối Redis | `docker compose logs worker`; `docker compose restart worker beat` |
| VS Code không attach được | Stack chạy bằng `make dev` (không có debugpy) | `make debug` (khoảng 30 giây), hoặc bỏ phần debug, chỉ mở `launch.json` |
| Breakpoint không dừng | Breakpoint đặt ở file ngoài `src/`, hoặc đã đặt lại sai dòng | Đặt lại ở `src/app/modules/reports/service.py` dòng 50 |
| Id khác với kịch bản | Seed không có `--reset`, hoặc đã tạo thêm dữ liệu | Xem id ở `GET /admin/users`, `GET /admin/departments` |

Phương án cuối nếu môi trường hỏng hẳn: chiếu video quay sẵn từng cảnh và mở trang Actions để chứng minh test vẫn xanh.
