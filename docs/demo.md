# Kịch bản demo

Demo 45 phút, hỏi đáp 15 phút, 8 cảnh. Mọi thao tác trên Swagger UI và Mailpit, trừ một lệnh CLI ở cảnh 7. Mỗi cảnh chỉ đi những bước chứng minh quy tắc chính của chức năng; quy tắc còn lại nằm ở mục "Nói gì" và phần hỏi đáp.

Kịch bản đã chạy thử trên stack Docker với dữ liệu `seed --reset`: mã HTTP, mã lỗi, tiêu đề email ghi dưới đây là kết quả thật. Id trong kịch bản đúng khi seed bằng `--reset` (id bắt đầu lại từ 1).

## Chuẩn bị

**Một lần, trước buổi demo:** chạy stack theo mục "Chạy nhanh" của README (`make dev`), mở http://localhost:8001/health thấy `"status": "ok"`.

**Sáng ngày demo**, khoảng 2 phút:

```bash
docker compose exec api daily-report seed --reset -y --password Matkhau@123
```

Seed tạo lại dữ liệu theo ngày chạy lệnh: tài khoản có từ ngày đầu tháng trước, báo cáo các ngày làm việc từ đó đến hôm qua (mỗi nhân viên bỏ trống khoảng 1/5 số ngày), chưa ai có báo cáo hôm nay. Seed từ hôm trước thì cảnh 3 nhận 409 vì báo cáo "hôm nay" đã tạo lúc tổng duyệt.

**15 phút trước giờ demo:**

- [ ] `docker compose ps`: `api` healthy; `worker`, `beat`, `postgres`, `redis`, `mailpit` đang chạy.
- [ ] Mailpit (http://localhost:8026): xóa hết thư (nút Delete all).
- [ ] Mở 4 tab Swagger (http://localhost:8001/docs), mỗi tab bấm **Authorize** một tài khoản: `an.nguyen`, `giang.vo`, `manager.dev`, `admin` (đều `@example.com`, mật khẩu `Matkhau@123`). Mỗi tab giữ token riêng.
- [ ] Mở sẵn trang Actions của repo, một lần chạy CI xanh (cảnh 8).

File dùng trong buổi demo có sẵn ở [`docs/demo-files/`](demo-files/): `avatar.png` (cảnh 2), `import-loi.xlsx` và `import-dung.xlsx` (cảnh 7).

Access token hết hạn sau 15 phút. Swagger báo 401 giữa buổi thì bấm **Authorize** → **Logout** → đăng nhập lại, mất vài giây.

## Tài khoản và id

| Id | Tài khoản (`@example.com`) | Role | Bộ phận | Vai trong demo |
| --- | --- | --- | --- | --- |
| 1 | `admin` | ADMIN | — | Quản lý tài khoản, bộ phận, import |
| 2 | `manager.dev` | MANAGER | DEV (id 1) | Manager chính |
| 3 | `manager.qa` | MANAGER | QA (id 2) | Người nhận không hợp lệ của An |
| 4 | `manager.hr` | MANAGER | HR (id 3) | |
| 5 | `an.nguyen` | USER | DEV | Nhân viên chính: hồ sơ, báo cáo |
| 6 | `binh.tran` | USER | DEV | Đồng nghiệp của An: "Chưa nộp" trong file export |
| 7 | `cuong.le` | USER | QA | Ngoài phạm vi của manager.dev |
| 8 | `dung.pham` | USER | QA | |
| 9 | `giang.vo` | USER | HR | Đổi mật khẩu |

Tạo trong buổi demo: tài khoản `eve.tran` (id 10, cảnh 5), bộ phận BA (id 4, cảnh 6), hai tài khoản import (id 11, 12, cảnh 7).

## Lịch trình

| Phút | Cảnh | Chức năng | Ý cần người xem nhớ |
| --- | --- | --- | --- |
| 00–03 | 1. Giới thiệu | — | Bài toán, kiến trúc, phạm vi |
| 03–10 | 2. Đăng nhập, hồ sơ | U1, U2 | Refresh token dùng một lần; không tự nâng quyền; đổi mật khẩu thu hồi phiên cũ |
| 10–17 | 3. Nhân viên tạo báo cáo | U3, S1 | Quy tắc ngày, người nhận, mỗi ngày một báo cáo, email qua worker |
| 17–24 | 4. Manager theo dõi bộ phận | M1, M3, M4, M5 | Chỉ thấy bộ phận mình quản lý; ngoài phạm vi là 404; export Excel |
| 24–30 | 5. Admin quản lý tài khoản | A1, S2 | Tài khoản mới tự đặt mật khẩu qua email; quy tắc bảo vệ admin, manager |
| 30–36 | 6. Admin quản lý bộ phận | A2, A3, M2 | Mã duy nhất, gán manager, manager tự thêm nhân viên, không xóa bộ phận còn người |
| 36–41 | 7. Import, thống kê tháng | A4, S3 | File có lỗi thì không tạo ai; chạy lại không gửi trùng |
| 41–45 | 8. Chất lượng, bàn giao | — | Test, CI, việc còn lại |
| 45–60 | Hỏi đáp | — | |

## 1. Giới thiệu (3 phút)

- Bài toán: nhân viên gửi báo cáo công việc hằng ngày cho manager bộ phận; manager theo dõi, export; admin quản lý tài khoản, bộ phận; hệ thống tự gửi email.
- Kiến trúc (`docs/architecture.md`): FastAPI + SQLAlchemy async trên PostgreSQL; Redis giữ trạng thái phiên, khóa tạm và làm hàng đợi cho Celery; worker gửi email qua SMTP (Mailpit khi dev); Celery Beat chạy lịch thống kê tháng. Modular monolith: mỗi module router → service → repository.
- API nhóm theo vai: `/auth`, `/me`, `/manager`, `/admin`, 41 endpoint. Mở `/docs`: endpoint có mô tả, ví dụ request, response, ví dụ cho từng mã lỗi.

## 2. Đăng nhập, hồ sơ (U1, U2, 7 phút)

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

## 3. Nhân viên tạo báo cáo (U3, S1, 7 phút)

Body tạo báo cáo (thay `<hôm nay>` bằng ngày hôm nay, dạng `2026-11-23`):

```json
{
  "report_date": "<hôm nay>",
  "planned_work": "Hoàn thành API xuất báo cáo Excel",
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

Nói gì:

- Người nhận là manager của bộ phận mình (Q4), không gửi `recipient_ids` là gửi tất cả. Báo cáo được lùi tối đa 3 ngày (Q6), không cho ngày tương lai, không trước ngày tạo tài khoản; đã gửi thì không sửa, xóa (Q5). Chỉ role USER viết báo cáo (Q3): manager, admin gọi trả 403.
- Mỗi người một báo cáo mỗi ngày nhờ unique index: hai request cùng lúc cũng chỉ một request thành công.
- Báo cáo và người nhận lưu trong một transaction; commit xong mới đẩy task email vào Redis. Redis lỗi thì báo cáo vẫn lưu, API vẫn trả 201; SMTP lỗi thì worker thử lại tối đa 3 lần.
- Lịch sử ở `GET /me/reports`, mới nhất trước. Báo cáo của người khác trả 404, không phải 403: không dò được id nào tồn tại.

Thiếu giờ: bỏ bước người nhận ngoài bộ phận.

## 4. Manager theo dõi bộ phận (M1, M3, M4, M5, 7 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| manager.dev | `GET /manager/departments` | | 200, chỉ DEV |
| manager.dev | `GET /manager/reports` | `keyword` `nguyen` | 200, báo cáo của Nguyễn Văn An (tìm không dấu) |
| manager.dev | `GET /manager/reports/{id}` | Id báo cáo An vừa tạo | 200, có bộ phận lúc viết, người nhận |
| manager.dev | `GET /manager/employees/7` | cuong.le (QA) | 404 `NOT_FOUND` |
| manager.dev | `GET /manager/reports/export` | Bỏ trống `date` (hôm nay) | File `bao-cao-<hôm nay>.xlsx`: An "Đã nộp", Bình "Chưa nộp" (ô đỏ) |
| manager.dev | `GET /admin/users` | | 403 `FORBIDDEN` |

Nói gì:

- Phạm vi là bộ phận admin gán cho manager, một chỗ định nghĩa (`ManagedDepartment`), áp dụng cho mọi endpoint `/manager`. Ngoài phạm vi (bộ phận, nhân viên, báo cáo khác) trả 404 giống không tồn tại.
- Báo cáo thuộc bộ phận lúc viết: nhân viên chuyển bộ phận thì báo cáo cũ vẫn ở bộ phận cũ.
- Danh sách đều phân trang; số câu SQL không đổi theo số dòng (có test đếm câu SQL); index `(department_id, report_date)`.
- Export ngày khác bằng tham số `date`. File tạo bằng openpyxl write-only, đọc xong trả kết nối DB rồi mới ghi file, gửi dạng stream. Nội dung người dùng nhập luôn là chữ, không thành công thức Excel.

Thiếu giờ: bỏ bước `GET /admin/users`.

## 5. Admin quản lý tài khoản (A1, S2, 6 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `GET /admin/users` | `role` MANAGER | 200, 3 manager |
| admin | `POST /admin/users` | `{"email": "eve.tran@example.com", "full_name": "Trần Thị Eve", "role": "USER"}` | 201, id 10 |
| admin | `POST /admin/users` | `{"email": "EVE.TRAN@example.com", "full_name": "Eve 2"}` | 409 `EMAIL_ALREADY_EXISTS` |
| Mailpit | | | Email "[Daily Report API] Đặt mật khẩu cho tài khoản của bạn" tới eve; chép giá trị `token` trên link |
| admin | `POST /auth/setup-password` | `{"token": "<token>", "password": "Eve@12345"}` | 204; eve đăng nhập được bằng mật khẩu này |
| admin | `PATCH /admin/users/1` | `{"role": "USER"}` (chính mình) | 400 `CANNOT_MODIFY_OWN_ACCOUNT` |
| admin | `PATCH /admin/users/2` | `{"role": "USER"}` (manager.dev đang quản lý DEV) | 409 `USER_MANAGES_DEPARTMENTS` |

Nói gì:

- Admin không đặt mật khẩu hộ (Q8): user nhận link dùng một lần (dùng lại trả 400), hết hạn 24 giờ, token chỉ lưu dạng băm. Link hết hạn thì admin gửi lại (`POST /admin/users/{id}/setup-link`).
- Email không phân biệt hoa thường. Xóa user là xóa mềm, giữ báo cáo cũ (Q9). Khóa, xóa tài khoản có hiệu lực ngay ở request kế tiếp.
- Luôn còn ít nhất một admin đăng nhập được; manager đang quản lý bộ phận phải được gỡ trước khi hạ role, khóa, xóa.

Thiếu giờ: bỏ bước email trùng, bước tự hạ quyền.

## 6. Admin quản lý bộ phận (A2, A3, M2, 6 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `POST /admin/departments` | `{"code": "ba", "name": "Phân tích nghiệp vụ"}` | 201, id 4, `code` lưu là `BA` |
| admin | `POST /admin/departments` | `{"code": "BA", "name": "Khác"}` | 409 `DEPARTMENT_CODE_ALREADY_EXISTS` |
| admin | `POST /admin/departments/4/managers` | `{"user_id": 5}` (an, role USER) | 422 `MANAGER_ROLE_REQUIRED` |
| admin | `POST /admin/departments/4/managers` | `{"user_id": 2}` | 200; manager.dev giờ quản lý DEV và BA |
| manager.dev | `POST /manager/departments/4/members` | `{"user_ids": [10]}` (eve, chưa thuộc bộ phận nào) | 204 |
| manager.dev | `POST /manager/departments/4/members` | `{"user_ids": [7]}` (cuong.le, đang ở QA) | 422 `INVALID_MEMBER_CANDIDATE` |
| admin | `DELETE /admin/departments/4` | BA còn eve | 409 `DEPARTMENT_NOT_EMPTY`, `member_count` 1 |

Nói gì:

- Một bộ phận nhiều manager, một manager nhiều bộ phận (Q2).
- Manager chỉ thêm được USER chưa thuộc bộ phận nào (danh sách ở `GET /manager/candidates`); thêm lại người đã thêm không lỗi, nên client gửi lại khi timeout vẫn an toàn.
- Xóa bộ phận là xóa mềm, chỉ khi không còn thành viên. Gán manager, thêm thành viên khóa dòng bộ phận nên không chạy xen với lệnh xóa; hai manager cùng thêm một người thì người sau nhận 422, không ghi đè.

Thiếu giờ: bỏ bước gán an, bước thêm cuong.le.

## 7. Import nhân viên, thống kê tháng (A4, S3, 5 phút)

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
| admin | `POST /admin/users/import` | `import-loi.xlsx` | 422 `IMPORT_VALIDATION_FAILED`: dòng 3 `email` đã dùng, dòng 4 `department_code` không có; không tạo ai |
| admin | `POST /admin/users/import` | `import-dung.xlsx` | 201, `created_count` 2; Mailpit có email đặt mật khẩu tới hoa.nguyen, khoa.le |
| Terminal | `docker compose exec api daily-report send-monthly-summary` | | Mailpit: 3 email "[Daily Report API] Thống kê báo cáo tháng MM/YYYY của bộ phận ..." (tháng trước), mỗi bộ phận một email gửi manager của bộ phận đó |
| Terminal | Chạy lại lệnh trên | | Không có email mới; `docker compose logs worker`: dòng `monthly_summary_done` có `already_sent=3`, `sent=0` |

Nói gì:

- Import kiểm tra cả file rồi mới ghi trong một transaction, trả mọi lỗi theo dòng một lần; tối đa 2 MB, 1.000 dòng; chặn file zip giải nén quá lớn, file không phải .xlsx (415).
- Thống kê: Celery Beat đẩy task 08:00 ngày 1 hằng tháng (giờ Việt Nam), chạy lại ngày 2, 3 để gửi bù email lỗi; mỗi email giữ `dedup_key` nên chạy lại không gửi trùng. Email liệt kê từng nhân viên đã nộp bao nhiêu ngày trên số ngày làm việc: thứ 2 đến thứ 6, chưa trừ ngày lễ (Q12); nhân viên mới tính từ ngày tạo tài khoản.

Thiếu giờ: chỉ chạy lệnh thống kê một lần.

## 8. Chất lượng, bàn giao (4 phút)

- Hơn 1.200 test chạy trên PostgreSQL, Redis thật (unit, DB, API, e2e), coverage trên 99%. Có test riêng cho ma trận quyền theo bộ phận, số câu SQL của mọi danh sách, hai transaction chạy đồng thời, mốc giờ theo giờ Việt Nam.
- Chỉ vào trang Actions đã mở sẵn: mỗi PR chạy ruff, mypy strict, pytest trên PostgreSQL thật; coverage dưới 80% thì đỏ.
- UAT ngày 22/11: đi hết các luồng theo vai, Postman collection (`docs/postman/`) gọi mọi endpoint, gửi dữ liệu lạ tới mọi endpoint; 3 lỗi tìm thấy đã sửa.
- Đã xong 15/15 chức năng; việc còn lại, giới hạn đã biết ở `docs/progress/handover.md`.

## Hỏi đáp: câu hỏi có thể gặp

**Hai request tạo báo cáo cùng lúc thì sao?** Unique `(author_id, report_date)` trong DB: một request thành công, request kia nhận 409, không phải 500. Các chỗ ghi đồng thời khác (gán manager, thêm thành viên, khóa admin cuối cùng) khóa dòng theo thứ tự cố định, có test chạy hai transaction thật.

**Manager gọi id ngoài phạm vi sao trả 404 chứ không phải 403?** Để không dò được id nào là bộ phận, nhân viên, báo cáo có thật. Thứ tự lỗi cố định: 401 → 403 (sai role) → 422 tham số URL → 404 phạm vi → 422 body.

**Đổi role, khóa tài khoản có hiệu lực ngay không?** Có. Role đọc từ DB ở mỗi request; khóa, xóa, đổi mật khẩu tăng `token_version` nên token cũ bị từ chối ở request kế tiếp.

**Redis hoặc SMTP lỗi thì sao?** Tạo báo cáo, tạo user vẫn thành công (201), lỗi đẩy task chỉ ghi log. SMTP lỗi thì worker thử lại 3 lần (30s, 60s, 120s), hết lượt ghi `email_logs` `FAILED`. `/health` trả 503 khi DB hoặc Redis lỗi.

**Vì sao báo cáo lưu `department_id` riêng?** Giữ lịch sử: nhân viên chuyển bộ phận thì báo cáo cũ vẫn thuộc bộ phận cũ, manager cũ vẫn xem được.

**Hiệu năng khi dữ liệu lớn?** Test đếm câu SQL cho mọi danh sách; danh sách báo cáo của manager đọc index `(department_id, report_date) INCLUDE (author_id, id)`. Số đo `EXPLAIN ANALYZE` trên 2,47 triệu báo cáo ở `docs/database.md`.

**Bảo mật?** Checklist theo OWASP API Security Top 10 ([security.md](security.md)): phân quyền mọi endpoint có test duyệt route thật, giới hạn dung lượng body, log không ghi mật khẩu, token. Dữ liệu lạ (ký tự NUL, số quá lớn, file giả) trả 4xx, không trả 500.

**Chưa làm gì?** Sửa báo cáo, quên mật khẩu, frontend, deploy thật nằm ngoài phạm vi (`docs/requirements.md` mục 3). Danh sách đầy đủ ở `docs/progress/handover.md`.

## Khi có sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| Swagger báo 401 giữa buổi | Access token hết hạn (15 phút), hoặc phiên bị thu hồi (gửi lại refresh token cũ sau 30 giây, đổi mật khẩu) | **Authorize** → **Logout** → đăng nhập lại |
| Đăng nhập trả 429 | Sai mật khẩu 5 lần với email đó | Chờ theo `Retry-After` (tối đa 15 phút) hoặc dùng tài khoản khác |
| Tạo báo cáo hôm nay trả 409 ngay lần đầu | Đã tạo lúc tổng duyệt | `seed --reset` (mục Chuẩn bị), hoặc dùng `binh.tran` |
| Đăng nhập trả 401 với tài khoản mẫu | Seed lần đầu bằng mật khẩu khác | `seed --reset -y --password Matkhau@123` |
| Không thấy email trên Mailpit | Worker chưa chạy hoặc mất kết nối Redis | `docker compose logs worker`; `docker compose restart worker beat` |
| Id khác với kịch bản | Seed không có `--reset`, hoặc đã tạo thêm dữ liệu | Xem id ở `GET /admin/users`, `GET /admin/departments` |
