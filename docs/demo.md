# Kịch bản demo

Demo 45 phút, hỏi đáp 15 phút. Mọi thao tác trên Swagger UI và Mailpit, trừ một lệnh CLI ở cảnh thống kê tháng. Kịch bản đi đủ 15 chức năng (U1–U3, M1–M5, A1–A4, S1–S3), mỗi cảnh có cả luồng thành công và các lỗi hệ thống phải chặn.

Kịch bản đã chạy thử trọn vẹn trên stack Docker với dữ liệu `seed --reset`: mã HTTP, mã lỗi, tiêu đề email ghi dưới đây là kết quả thật. Id trong kịch bản đúng khi seed bằng `--reset` (id bắt đầu lại từ 1).

## Chuẩn bị

**Một lần, trước buổi demo:** chạy stack theo mục "Chạy nhanh" của README (`make dev`), mở http://localhost:8001/health thấy `"status": "ok"`.

**Sáng ngày demo**, khoảng 2 phút:

```bash
docker compose exec api daily-report seed --reset -y --password Matkhau@123
```

Seed tạo lại dữ liệu theo ngày chạy lệnh: tài khoản có từ ngày đầu tháng trước, báo cáo các ngày làm việc từ đó đến hôm qua (mỗi nhân viên bỏ trống khoảng 1/5 số ngày), chưa ai có báo cáo hôm nay. Seed từ hôm trước thì cảnh 4 nhận 409 vì báo cáo "hôm nay" đã tạo lúc tổng duyệt.

**15 phút trước giờ demo:**

- [ ] `docker compose ps`: `api` healthy; `worker`, `beat`, `postgres`, `redis`, `mailpit` đang chạy.
- [ ] Mailpit (http://localhost:8026): xóa hết thư (nút Delete all).
- [ ] Mở 4 tab Swagger (http://localhost:8001/docs), mỗi tab bấm **Authorize** một tài khoản: `an.nguyen`, `giang.vo`, `manager.dev`, `admin` (đều `@example.com`, mật khẩu `Matkhau@123`). Mỗi tab giữ token riêng.
- [ ] File cho cảnh 3: một ảnh PNG hoặc JPEG dưới 2 MB; một file text đổi đuôi thành `.png`.
- [ ] File cho cảnh 9: tải `GET /api/v1/admin/users/import-template` (tab admin), điền và lưu thành hai file theo bảng ở cảnh 9.
- [ ] Mở sẵn trang Actions của repo, một lần chạy CI xanh (cảnh 11).

Access token hết hạn sau 15 phút. Swagger báo 401 giữa buổi thì bấm **Authorize** → **Logout** → đăng nhập lại, mất vài giây.

## Tài khoản và id

| Id | Tài khoản (`@example.com`) | Role | Bộ phận | Vai trong demo |
| --- | --- | --- | --- | --- |
| 1 | `admin` | ADMIN | — | Quản lý tài khoản, bộ phận, import |
| 2 | `manager.dev` | MANAGER | DEV (id 1) | Manager chính |
| 3 | `manager.qa` | MANAGER | QA (id 2) | Người nhận không hợp lệ của DEV |
| 4 | `manager.hr` | MANAGER | HR (id 3) | |
| 5 | `an.nguyen` | USER | DEV | Nhân viên chính: hồ sơ, báo cáo |
| 6 | `binh.tran` | USER | DEV | Đồng nghiệp của An: "Chưa nộp" trong file export |
| 7 | `cuong.le` | USER | QA | Nhân viên ngoài phạm vi của manager.dev |
| 8 | `dung.pham` | USER | QA | |
| 9 | `giang.vo` | USER | HR | Đổi mật khẩu; không xem được báo cáo của An; bị khóa thử |

Tài khoản tạo trong buổi demo: `eve.tran` (id 10, cảnh 6), bộ phận BA (id 4, cảnh 8), hai tài khoản import (id 11, 12, cảnh 9).

## Lịch trình

| Phút | Cảnh | Chức năng | Ý cần người xem nhớ |
| --- | --- | --- | --- |
| 00–03 | 1. Giới thiệu | — | Bài toán, kiến trúc, phạm vi |
| 03–09 | 2. Đăng nhập, phiên | U1 | Refresh token dùng một lần, khóa tạm khi sai nhiều lần, đăng xuất có hiệu lực ngay |
| 09–14 | 3. Hồ sơ cá nhân | U2 | Không tự nâng quyền; ảnh xét theo nội dung; đổi mật khẩu thu hồi phiên cũ |
| 14–21 | 4. Nhân viên tạo báo cáo | U3, S1 | Quy tắc ngày, người nhận, mỗi ngày một báo cáo, email qua worker |
| 21–28 | 5. Manager theo dõi bộ phận | M1, M3, M4, M5 | Chỉ thấy bộ phận mình quản lý; ngoài phạm vi là 404; export Excel |
| 28–33 | 6. Admin quản lý tài khoản | A1, S2 | Tài khoản mới tự đặt mật khẩu qua email; các quy tắc bảo vệ admin, manager |
| 33–36 | 7. Manager thêm, gỡ nhân viên | M2 | Chỉ thêm người chưa thuộc bộ phận nào |
| 36–39 | 8. Admin quản lý bộ phận | A2, A3 | Mã duy nhất, gán manager, xóa mềm |
| 39–42 | 9. Import nhân viên | A4 | Kiểm tra cả file, có lỗi thì không tạo ai |
| 42–44 | 10. Thống kê tháng | S3 | Celery Beat, chạy lại không gửi trùng |
| 44–45 | 11. Chất lượng, bàn giao | — | Test, CI, tài liệu |
| 45–60 | Hỏi đáp | — | |

## 1. Giới thiệu (3 phút)

- Bài toán: nhân viên gửi báo cáo công việc hằng ngày cho manager bộ phận; manager theo dõi, export; admin quản lý tài khoản, bộ phận; hệ thống tự gửi email.
- Kiến trúc (`docs/architecture.md`): FastAPI + SQLAlchemy async trên PostgreSQL; Redis giữ trạng thái phiên, khóa tạm và làm hàng đợi cho Celery; worker gửi email qua SMTP (Mailpit khi dev); Celery Beat chạy lịch thống kê tháng. Modular monolith: mỗi module router → service → repository.
- API nhóm theo vai: `/auth`, `/me`, `/manager`, `/admin`, 41 endpoint. Mở `/docs`: endpoint có mô tả, ví dụ request, response, ví dụ cho từng mã lỗi.

## 2. Đăng nhập, phiên (U1, 6 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| an | `POST /auth/login` (Try it out) | `username` `an.nguyen@example.com`, `password` `Matkhau@123` | 200, `access_token`, `refresh_token`, `expires_in` 900 |
| an | `POST /auth/refresh` | `{"refresh_token": "<token vừa nhận>"}` | 200, cặp token mới |
| an | `POST /auth/refresh` | Gửi lại đúng refresh token cũ, ngay sau bước trên | 401 `UNAUTHORIZED` |
| an | `POST /auth/login` | `username` `khong.ton.tai@example.com`, mật khẩu sai, bấm 6 lần | 5 lần 401 `INVALID_CREDENTIALS`, lần 6: 429 `TOO_MANY_ATTEMPTS`, header `Retry-After` |
| an | `POST /auth/logout` | | 204 |
| an | `GET /me` | Token vừa đăng xuất | 401; **Authorize** lại `an.nguyen` |

Nói gì:

- Refresh token xoay vòng, mỗi token dùng một lần. Gửi lại token cũ trong 30 giây (client timeout rồi gửi lại) chỉ bị từ chối; sau 30 giây bị coi là token bị lộ: mọi phiên của tài khoản bị thu hồi.
- Khóa tạm đếm theo email, kể cả email không tồn tại (không dò được email nào có thật), 15 phút. Demo dùng email không tồn tại để không khóa tài khoản thật.
- Đăng xuất thu hồi cả phiên: refresh token trong DB, access token qua blacklist Redis, không phải chờ hết hạn.

Thiếu giờ: bỏ bước khóa tạm.

## 3. Hồ sơ cá nhân (U2, 5 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| an | `GET /me` | | 200, `role` USER, `department` DEV, `avatar_url` null |
| an | `PATCH /me` | `{"role": "ADMIN"}` | 422 `VALIDATION_ERROR`, field `body.role` |
| an | `PATCH /me` | `{"phone": "0912345678"}` | 200 |
| an | `PUT /me/avatar` | Ảnh PNG/JPEG | 200, `avatar_url`; mở link thấy ảnh |
| an | `PUT /me/avatar` | File text đổi đuôi `.png` | 415 `UNSUPPORTED_FILE_TYPE` |
| giang | `PUT /me/password` | `{"current_password": "Sai@1234", "new_password": "Moi@12345"}` | 400 `CURRENT_PASSWORD_INCORRECT` |
| giang | `PUT /me/password` | `{"current_password": "Matkhau@123", "new_password": "Moi@12345"}` | 200, cặp token mới |
| giang | `GET /me` | Token cũ của tab | 401; **Authorize** lại bằng mật khẩu `Moi@12345` |

Nói gì:

- Sửa hồ sơ từng phần; field không được sửa (email, role) hay field lạ trả 422, không bỏ qua âm thầm.
- Loại ảnh xét theo nội dung file (magic bytes), không theo đuôi hay `Content-Type`. Ảnh lưu local hoặc S3, đổi bằng cấu hình.
- Đổi mật khẩu tăng `token_version`: mọi phiên khác hết hiệu lực ngay, phiên hiện tại nhận token mới.

Thiếu giờ: bỏ bước file text, bước sai mật khẩu.

## 4. Nhân viên tạo báo cáo (U3, S1, 7 phút)

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
| an | `GET /me/reports` | | 200, báo cáo mới nhất trước, có `meta.total` |
| giang | `GET /me/reports/{id}` | Id báo cáo An vừa tạo | 404 `NOT_FOUND` |
| manager.dev | `POST /me/reports` | Body trên | 403 `FORBIDDEN` |

Nói gì:

- Người nhận là manager của bộ phận mình (Q4), không gửi `recipient_ids` là gửi tất cả. Báo cáo được lùi tối đa 3 ngày (Q6), không cho ngày tương lai, không trước ngày tạo tài khoản; đã gửi thì không sửa, xóa (Q5). Chỉ role USER viết báo cáo (Q3).
- Mỗi người một báo cáo mỗi ngày nhờ unique index: hai request cùng lúc cũng chỉ một request thành công.
- Báo cáo và người nhận lưu trong một transaction; commit xong mới đẩy task email vào Redis. Redis lỗi thì báo cáo vẫn lưu, API vẫn trả 201; SMTP lỗi thì worker thử lại tối đa 3 lần.
- Báo cáo của người khác trả 404, không phải 403: không dò được id nào tồn tại.

Thiếu giờ: bỏ bước giang, bước manager.

## 5. Manager theo dõi bộ phận (M1, M3, M4, M5, 7 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| manager.dev | `GET /manager/departments` | | 200, chỉ DEV |
| manager.dev | `GET /manager/departments/1` | | 200, `managers`, `member_count` 3 |
| manager.dev | `GET /manager/departments/2` | QA | 404 `NOT_FOUND`, field `department_id` |
| manager.dev | `GET /manager/reports` | `keyword` `nguyen` | 200, báo cáo của Nguyễn Văn An (tìm không dấu) |
| manager.dev | `GET /manager/reports/{id}` | Id báo cáo An vừa tạo | 200, có bộ phận lúc viết, người nhận |
| manager.dev | `GET /manager/reports` | `department_id` 2 | 404 `NOT_FOUND` |
| manager.dev | `GET /manager/employees/7` | cuong.le (QA) | 404 `NOT_FOUND` |
| manager.dev | `GET /manager/reports/export` | Bỏ trống `date` (hôm nay) | File `bao-cao-<hôm nay>.xlsx`: An "Đã nộp", Bình "Chưa nộp" (ô đỏ) |
| manager.dev | `GET /manager/reports/export` | `date` là một ngày làm việc tuần trước | File của ngày đó; nhân viên bỏ trống ngày đó là "Chưa nộp" (dữ liệu mẫu: tuần nào cũng có) |
| manager.dev | `GET /admin/users` | | 403 `FORBIDDEN` |

Nói gì:

- Phạm vi là bộ phận admin gán cho manager, một chỗ định nghĩa (`ManagedDepartment`), áp dụng cho mọi endpoint `/manager`. Ngoài phạm vi trả 404 giống không tồn tại.
- Báo cáo thuộc bộ phận lúc viết: nhân viên chuyển bộ phận thì báo cáo cũ vẫn ở bộ phận cũ.
- Danh sách đều phân trang; số câu SQL không đổi theo số dòng (có test đếm câu SQL); index `(department_id, report_date)`.
- Export: openpyxl write-only, đọc xong trả kết nối DB rồi mới ghi file, gửi dạng stream. Nội dung người dùng nhập luôn là chữ, không thành công thức Excel.

Thiếu giờ: bỏ bước `department_id` 2, bước export ngày cũ.

## 6. Admin quản lý tài khoản (A1, S2, 5 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `GET /admin/users` | `role` MANAGER | 200, 3 manager |
| admin | `POST /admin/users` | `{"email": "eve.tran@example.com", "full_name": "Trần Thị Eve", "role": "USER"}` | 201, id 10 |
| admin | `POST /admin/users` | `{"email": "EVE.TRAN@example.com", "full_name": "Eve 2"}` | 409 `EMAIL_ALREADY_EXISTS` |
| Mailpit | | | Email "[Daily Report API] Đặt mật khẩu cho tài khoản của bạn" tới eve; chép giá trị `token` trên link |
| admin | `POST /auth/setup-password` | `{"token": "<token>", "password": "Eve@12345"}` | 204 |
| admin | `POST /auth/setup-password` | Gửi lại | 400 `SETUP_TOKEN_INVALID` |
| admin | `POST /auth/login` (Try it out) | `eve.tran@example.com` / `Eve@12345` | 200 |
| admin | `PATCH /admin/users/1` | `{"role": "USER"}` (chính mình) | 400 `CANNOT_MODIFY_OWN_ACCOUNT` |
| admin | `PATCH /admin/users/2` | `{"role": "USER"}` (manager.dev đang quản lý DEV) | 409 `USER_MANAGES_DEPARTMENTS` |
| admin | `PATCH /admin/users/9` | `{"is_active": false}` | 200; tab giang `GET /me` trả 401 ngay |
| admin | `PATCH /admin/users/9` | `{"is_active": true}` | 200; tab giang **Authorize** lại (`Moi@12345`) |

Nói gì:

- Admin không đặt mật khẩu hộ (Q8): user nhận link dùng một lần, hết hạn 24 giờ, token chỉ lưu dạng băm. Link hết hạn thì admin gửi lại (`POST /admin/users/{id}/setup-link`).
- Email không phân biệt hoa thường. Xóa user là xóa mềm, giữ báo cáo cũ (Q9).
- Luôn còn ít nhất một admin đăng nhập được; manager đang quản lý bộ phận phải được gỡ trước khi hạ role, khóa, xóa.

Thiếu giờ: bỏ bước email trùng, bước khóa giang.

## 7. Manager thêm, gỡ nhân viên (M2, 3 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| manager.dev | `GET /manager/candidates` | | 200, chỉ eve (USER chưa thuộc bộ phận nào) |
| manager.dev | `POST /manager/departments/1/members` | `{"user_ids": [10]}` | 204 |
| manager.dev | `POST /manager/departments/1/members` | `{"user_ids": [7]}` (cuong.le, đã ở QA) | 422 `INVALID_MEMBER_CANDIDATE` |
| manager.dev | `GET /manager/departments/1/members` | | Có eve |
| manager.dev | `DELETE /manager/departments/1/members/10` | | 204, eve quay lại danh sách ứng viên |

Nói gì: thêm lại người đã thêm không lỗi (client gửi lại khi timeout vẫn an toàn); hai manager cùng thêm một người thì người sau nhận 422, không ghi đè.

## 8. Admin quản lý bộ phận (A2, A3, 3 phút)

| Tab | Request | Body, tham số | Kết quả |
| --- | --- | --- | --- |
| admin | `POST /admin/departments` | `{"code": "ba", "name": "Phân tích nghiệp vụ"}` | 201, id 4, `code` lưu là `BA` |
| admin | `POST /admin/departments` | `{"code": "BA", "name": "Khác"}` | 409 `DEPARTMENT_CODE_ALREADY_EXISTS` |
| admin | `GET /admin/departments` | `keyword` `phan tich` | 200, có BA (tìm không dấu) |
| admin | `POST /admin/departments/4/managers` | `{"user_id": 5}` (an, role USER) | 422 `MANAGER_ROLE_REQUIRED` |
| admin | `POST /admin/departments/4/managers` | `{"user_id": 2}` | 200; tab manager.dev `GET /manager/departments` thấy BA và DEV |
| admin | `DELETE /admin/departments/1` | DEV còn thành viên | 409 `DEPARTMENT_NOT_EMPTY`, `member_count` |
| admin | `DELETE /admin/departments/4/managers/2`, rồi `DELETE /admin/departments/4` | | 204, 204; `GET /admin/departments/4` trả 404 |

Nói gì: một bộ phận nhiều manager, một manager nhiều bộ phận (Q2); xóa bộ phận là xóa mềm, chặn khi còn thành viên; gán manager, thêm thành viên khóa dòng bộ phận nên không chạy xen với lệnh xóa.

## 9. Import nhân viên từ Excel (A4, 3 phút)

Hai file làm từ file mẫu (giữ dòng tiêu đề, cột số điện thoại để dạng chữ):

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
| admin | `POST /admin/users/import` | `import-dung.xlsx` | 201, `created_count` 2 |
| Mailpit | | | Hai email đặt mật khẩu tới hoa.nguyen, khoa.le |

Nói gì: kiểm tra cả file rồi mới ghi trong một transaction, trả mọi lỗi theo dòng một lần; tối đa 2 MB, 1.000 dòng; chặn file zip giải nén quá lớn, file không phải .xlsx (415).

## 10. Thống kê tháng (S3, 2 phút)

```bash
docker compose exec api daily-report send-monthly-summary
```

| Ở đâu | Kết quả |
| --- | --- |
| Mailpit | 3 email "[Daily Report API] Thống kê báo cáo tháng MM/YYYY của bộ phận ..." (tháng trước), mỗi manager một email: từng nhân viên đã nộp bao nhiêu ngày trên số ngày làm việc |
| Chạy lại lệnh | Không có email mới: mỗi email giữ `dedup_key`, log worker `monthly_summary_done sent=0 already_sent=3` |

Nói gì: Celery Beat đẩy task 08:00 ngày 1 hằng tháng (giờ Việt Nam), chạy lại ngày 2, 3 để gửi bù email lỗi; ngày làm việc là thứ 2 đến thứ 6, chưa trừ ngày lễ (Q12); nhân viên mới tính từ ngày tạo tài khoản.

## 11. Chất lượng, bàn giao (1 phút)

Số liệu và việc còn lại ở `docs/progress/handover.md`. Chỉ vào trang Actions đã mở sẵn: mỗi PR chạy ruff, mypy strict, pytest trên PostgreSQL thật (coverage ≥ 80%). Postman collection ở `docs/postman/` gọi lại được mọi endpoint.

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
