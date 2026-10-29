# Thiết kế API

39 endpoint, nhóm theo người dùng: `/auth`, `/me`, `/manager`, `/admin`. Mỗi nhóm khớp một nhóm quyền trong requirement, nên dễ đối chiếu và dễ test phân quyền. Swagger tự sinh tại `/docs`.

## Quy ước

### URL và định dạng

- Tiền tố `/api/v1`. Riêng `/health` không có tiền tố để container healthcheck gọi trực tiếp.
- JSON snake_case. Ngày theo ISO 8601 (`2026-11-09`), thời điểm có múi giờ (`2026-11-09T08:30:00+07:00`).
- Xác thực: OAuth2 password flow + JWT. Header `Authorization: Bearer <access_token>`.
- `POST /auth/login` nhận form `application/x-www-form-urlencoded` với `username` (là email) và `password`, đúng chuẩn OAuth2, để nút **Authorize** trên Swagger đăng nhập được. Các endpoint khác nhận JSON.

### Phân quyền

- Nhóm `/admin` chỉ cho role ADMIN, nhóm `/manager` chỉ cho role MANAGER. Role được kiểm tra một lần ở cấp nhóm router bằng dependency `require_roles` (`app/api/deps.py`), endpoint trong nhóm không tự kiểm tra lại.
- Không có thứ bậc role: ADMIN gọi `/manager` cũng nhận 403, vì chức năng manager gắn với bộ phận mình quản lý.
- Thứ tự kiểm tra: token (401) → role (403) → phạm vi dữ liệu trong service (404).
- Role đọc từ user trong DB ở mỗi request, không từ claim `role` của token, nên đổi role có hiệu lực ngay.

### Danh sách có phân trang

Query: `page` (từ 1), `page_size` (mặc định 20, tối đa 100), `sort` (ví dụ `-report_date`), `keyword`.

```json
{
  "data": [{ "id": 128, "report_date": "2026-11-09" }],
  "meta": { "page": 1, "page_size": 20, "total": 135 }
}
```

### Lỗi

Mọi lỗi cùng một format:

```json
{
  "error": {
    "code": "REPORT_ALREADY_EXISTS",
    "message": "Bạn đã tạo báo cáo cho ngày 2026-11-09.",
    "details": null
  }
}
```

Lỗi validate (422) có `details` là danh sách `{ "field": "body.report_date", "message": "..." }`.

| HTTP | Khi nào |
| --- | --- |
| 200, 201, 204 | Thành công |
| 401 | Chưa đăng nhập, token hết hạn hoặc đã thu hồi |
| 403 | Sai role |
| 404 | Không tồn tại hoặc ngoài phạm vi quyền |
| 409 | Trùng dữ liệu |
| 422 | Dữ liệu không hợp lệ |
| 429 | Quá số lần thử |
| 500 | Lỗi hệ thống |

### Mã lỗi

| Mã | HTTP | Ngày |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | 1 |
| `NOT_FOUND` | 404 | 1 |
| `METHOD_NOT_ALLOWED` | 405 | 1 |
| `INTERNAL_ERROR` | 500 | 1 |
| `UNAUTHORIZED` | 401 | 1 |
| `FORBIDDEN` | 403 | 3 |
| `INVALID_CREDENTIALS` | 401 | 1 |
| `TOO_MANY_ATTEMPTS` | 429 | 3 |
| `CURRENT_PASSWORD_INCORRECT` | 400 | 3 |
| `EMAIL_ALREADY_EXISTS` | 409 | 4 |
| `DEPARTMENT_CODE_ALREADY_EXISTS` | 409 | 4 |
| `DEPARTMENT_NOT_EMPTY` | 409 | 4 |
| `REPORT_ALREADY_EXISTS` | 409 | 5 |
| `REPORT_DATE_OUT_OF_RANGE` | 422 | 5 |
| `INVALID_RECIPIENT` | 422 | 5 |
| `SETUP_TOKEN_INVALID` | 400 | 7 |
| `IMPORT_VALIDATION_FAILED` | 422 | 8 |

## Danh sách endpoint

### /auth: công khai, trừ logout (4)

| Method | Endpoint | Mã | Ghi chú |
| --- | --- | --- | --- |
| POST | `/auth/login` | U1 | Form `username`, `password`. Trả access token và refresh token. Sai quá 5 lần trong 15 phút: 429 |
| POST | `/auth/refresh` | U1 | Body `refresh_token`. Cấp cặp token mới, vô hiệu token cũ |
| POST | `/auth/logout` | U1 | Cần đăng nhập, thu hồi phiên hiện tại. Trả 204 |
| POST | `/auth/setup-password` | S2 | Đặt mật khẩu lần đầu bằng token trong email |

Phiên đăng nhập:

- Access token (15 phút) và refresh token (7 ngày) đều là JWT, phân biệt bằng claim `type`. Bảng `refresh_tokens` chỉ lưu `jti` của refresh token. Mỗi lần đăng nhập là một phiên có mã riêng (`session_id`), giữ nguyên qua các lần refresh; access token mang mã này trong claim `sid`.
- Refresh xoay vòng: mỗi refresh token chỉ dùng được một lần. Gửi lại token đã thu hồi (đã dùng hoặc đã đăng xuất) bị coi là token bị lộ: thu hồi mọi phiên của user và tăng `token_version`, mọi access token đang dùng cũng hết hiệu lực.
- Ngoại lệ: token gửi lại trong 30 giây kể từ lúc bị thu hồi (client timeout rồi gửi lại, hai tab cùng refresh) chỉ bị từ chối (401), không thu hồi phiên nào. Đánh đổi: kẻ trộm dùng token trước, chủ tài khoản gửi lại trong 30 giây đó thì không phát hiện được.
- Đăng xuất thu hồi cả phiên: mọi refresh token cùng `session_id` trong DB, và đưa mã phiên vào blacklist Redis trong 15 phút (thời hạn access token), nên mọi access token của phiên, kể cả token cấp trước lần refresh gần nhất, bị từ chối ngay. Các phiên trên thiết bị khác không bị ảnh hưởng.
- Khóa tạm đăng nhập đếm theo email (không phân biệt hoa thường, kể cả email không tồn tại), cửa sổ 15 phút tính từ lần thử đầu. Lần thứ 6 trả 429 `TOO_MANY_ATTEMPTS` kèm header `Retry-After` (số giây còn lại), không kiểm tra mật khẩu. Đăng nhập đúng thì xóa bộ đếm.

### /me: mọi user đã đăng nhập; báo cáo chỉ cho role USER (8)

| Method | Endpoint | Mã | Ghi chú |
| --- | --- | --- | --- |
| GET | `/me` | U2 | Gồm role và bộ phận |
| PATCH | `/me` | U2 | Sửa `full_name`, `phone`, `date_of_birth`. Không tự đổi được email, role |
| PUT | `/me/password` | U2 | Cần mật khẩu cũ. Trả cặp token mới cho phiên hiện tại |
| PUT | `/me/avatar` | U2 | `multipart/form-data`, JPEG hoặc PNG, tối đa 2 MB |
| GET | `/me/recipients` | U3 | Manager của bộ phận mình |
| POST | `/me/reports` | U3, S1 | Tạo báo cáo, kích hoạt email |
| GET | `/me/reports` | U3 | `date_from`, `date_to`, phân trang |
| GET | `/me/reports/{id}` | U3 | |

Hồ sơ cá nhân:

- `PATCH /me` cập nhật từng phần: field không gửi thì giữ nguyên, `null` xóa `phone`, `date_of_birth` (`full_name` bắt buộc, không nhận `null`). Gửi `email`, `role` hay field lạ trả 422, không bỏ qua âm thầm.
- `phone`: chỉ chữ số, có thể có `+` đầu, 9 đến 15 chữ số. `date_of_birth`: ngày trong quá khứ.
- Mật khẩu người dùng tự chọn (đổi mật khẩu, `create-admin`, đặt mật khẩu lần đầu): 8 đến 128 ký tự, có chữ thường, chữ hoa, chữ số và ký tự đặc biệt. Không đạt thì 422 ở field đó. Mật khẩu khi đăng nhập và mật khẩu hiện tại không xét quy tắc này.
- `PUT /me/password` body `current_password`, `new_password` (phải khác mật khẩu hiện tại). Sai mật khẩu hiện tại trả 400 `CURRENT_PASSWORD_INCORRECT` (không dùng 401 để client không hiểu nhầm là hết phiên), đếm chung với đăng nhập sai nên quá 5 lần trong 15 phút trả 429.
- Đổi mật khẩu tăng `token_version`: mọi access token, refresh token cũ (cả của phiên hiện tại) hết hiệu lực, response trả cặp token mới cho phiên hiện tại. Nếu trong lúc xử lý phiên đã hết hiệu lực (request đổi mật khẩu khác chạy trước, tài khoản bị khóa) thì trả 401. Refresh token cũ không bị đánh dấu thu hồi, để thiết bị khác refresh bằng token cũ chỉ nhận 401, không bị coi là token bị lộ (việc đó sẽ đăng xuất cả phiên vừa đổi mật khẩu).

### /manager: role MANAGER, chỉ bộ phận mình quản lý (11)

| Method | Endpoint | Mã | Ghi chú |
| --- | --- | --- | --- |
| GET | `/manager/departments` | M1 | |
| GET | `/manager/departments/{id}` | M1 | Gồm danh sách manager, số nhân viên |
| GET | `/manager/departments/{id}/members` | M1 | `keyword`, phân trang |
| GET | `/manager/candidates` | M2 | User role User chưa thuộc bộ phận nào |
| POST | `/manager/departments/{id}/members` | M2 | Body `user_ids[]` |
| DELETE | `/manager/departments/{id}/members/{user_id}` | M2 | Chỉ gỡ liên kết |
| GET | `/manager/employees` | M4 | `keyword`, `department_id`, phân trang |
| GET | `/manager/employees/{id}` | M4 | |
| GET | `/manager/reports` | M3 | `keyword`, `date_from`, `date_to`, `department_id`, `sort`, phân trang |
| GET | `/manager/reports/{id}` | M3 | |
| GET | `/manager/reports/export` | M5 | `date`, `department_id`, trả file .xlsx |

### /admin: role ADMIN (15)

| Method | Endpoint | Mã | Ghi chú |
| --- | --- | --- | --- |
| GET | `/admin/users` | A1 | `keyword`, `role`, `department_id`, phân trang |
| POST | `/admin/users` | A1, S2 | Tạo tài khoản, gửi link đặt mật khẩu |
| GET | `/admin/users/{id}` | A1 | |
| PATCH | `/admin/users/{id}` | A1 | Gồm gán bộ phận, khóa tài khoản |
| DELETE | `/admin/users/{id}` | A1 | Xóa mềm, thu hồi mọi phiên |
| GET | `/admin/users/import-template` | A4 | Tải file Excel mẫu |
| POST | `/admin/users/import` | A4 | Upload .xlsx |
| GET | `/admin/departments` | A2 | `keyword`, phân trang |
| POST | `/admin/departments` | A2 | |
| GET | `/admin/departments/{id}` | A2 | |
| PATCH | `/admin/departments/{id}` | A2 | |
| DELETE | `/admin/departments/{id}` | A2 | Xóa mềm, chặn khi còn thành viên |
| GET | `/admin/departments/{id}/members` | A3 | Xem thành viên để chọn manager |
| POST | `/admin/departments/{id}/managers` | A3 | Body `user_id`, user phải có role MANAGER |
| DELETE | `/admin/departments/{id}/managers/{user_id}` | A3 | |

Bộ phận (A2):

- `code` 1 đến 20 ký tự, chỉ chữ cái không dấu (ASCII), chữ số, `-`, `_`; trim và lưu chữ hoa (`qa` thành `QA`). Ký tự như `ß`, `ı` bị từ chối (422), không bị đổi ngầm thành `SS`, `I`. Không trùng với bộ phận chưa bị xóa, không phân biệt hoa thường: trùng trả 409 `DEPARTMENT_CODE_ALREADY_EXISTS`, `details` là `{"field": "code"}`. Mã của bộ phận đã xóa dùng lại được.
- `name` 1 đến 100 ký tự, `description` tối đa 1000 ký tự, cả hai được trim.
- `GET /admin/departments`: `keyword` tìm trong mã hoặc tên, không phân biệt hoa thường, không dấu (`ky thuat` khớp `Kỹ thuật`); sắp theo mã. Bộ phận đã xóa không hiện ở danh sách, xem, sửa, xóa (404, `details` là `{"field": "department_id"}`).
- `department_id` trên URL phải từ 1 đến 2^63 − 1 (phạm vi khóa chính bigint), ngoài phạm vi trả 422 ở field `path.department_id`.
- `PATCH` cập nhật từng phần như `PATCH /me`: `null` xóa `description`; `code`, `name` không nhận `null`; field lạ trả 422.
- `DELETE` xóa mềm, trả 204. Còn thành viên (user chưa bị xóa có `department_id` là bộ phận này, kể cả user bị khóa) thì trả 409 `DEPARTMENT_NOT_EMPTY`, `details` là `{"member_count": n}`. Xóa được thì liên kết manager của bộ phận bị gỡ luôn, giống ON DELETE CASCADE khi xóa cứng.

### Hệ thống (1 endpoint, 3 tác vụ nền)

| Loại | Tên | Mã | Ghi chú |
| --- | --- | --- | --- |
| GET | `/health` | — | Kiểm tra DB, Redis. 200 khi ổn, 503 khi có thành phần lỗi |
| Event | `send_report_notification` | S1 | Sau khi tạo báo cáo |
| Event | `send_account_setup_email` | S2 | Sau khi admin tạo user hoặc import |
| Cron | `send_monthly_summary` | S3 | 08:00 ngày 1 hằng tháng |

## Thứ tự khai báo route

Route tĩnh phải khai báo trước route có tham số trong cùng router, ví dụ `/admin/users/import-template` trước `/admin/users/{id}` và `/manager/reports/export` trước `/manager/reports/{id}`. Nếu không, FastAPI khớp nhầm vào `{id}` và trả 422.
