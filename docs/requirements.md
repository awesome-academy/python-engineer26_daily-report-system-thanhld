# Phân tích requirement

Nguồn: `[API project] Requirement Mock project.xlsx`, sheet "5. Daily Report".

Mã chức năng ghi theo vai trò: U (User), M (Manager), A (Admin), S (System). Mã này dùng trong task, nhánh git, commit và test. Mọi endpoint có tiền tố `/api/v1`. Chi tiết request, response xem `docs/api-design.md`.

## 1. Danh sách chức năng

### User (nhân viên)

| Mã | Ô Excel | Chức năng | Mức | Endpoint / Trigger | Kỹ thuật áp dụng |
| --- | --- | --- | --- | --- | --- |
| U1 | B4 | Đăng nhập, đăng xuất | Basic | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` | JWT: access token 15 phút, refresh token 7 ngày (lưu DB, đổi mới mỗi lần refresh). Argon2. Đăng xuất thu hồi refresh token và đưa access token vào blacklist Redis. Khóa tạm sau 5 lần đăng nhập sai trong 15 phút. |
| U2 | B5 | Xem, sửa thông tin cá nhân, đổi mật khẩu | Basic | `GET /me`, `PATCH /me`, `PUT /me/password`, `PUT /me/avatar` | PATCH cập nhật từng phần. Đổi mật khẩu cần mật khẩu cũ, sau đó tăng `token_version` để mọi phiên khác hết hiệu lực. Ảnh đại diện nhận qua `UploadFile` (JPEG, PNG, tối đa 2 MB), lưu local hoặc S3. |
| U3 | B6 | Tạo báo cáo hằng ngày | Basic | `GET /me/recipients`, `POST /me/reports`, `GET /me/reports`, `GET /me/reports/{id}` | Unique (người viết, ngày). Ngày báo cáo từ hôm nay trừ 3 ngày đến hôm nay. Lưu báo cáo và người nhận trong 1 transaction, sau commit mới đẩy task gửi mail. |

### Manager (chỉ trong các bộ phận mình quản lý)

| Mã | Ô Excel | Chức năng | Mức | Endpoint / Trigger | Kỹ thuật áp dụng |
| --- | --- | --- | --- | --- | --- |
| M1 | B8 | Quản lý thông tin bộ phận | Basic | `GET /manager/departments`, `GET /manager/departments/{id}`, `GET /manager/departments/{id}/members` | Policy phạm vi bộ phận dùng chung. Tìm tên tiếng Việt không dấu (unaccent, pg_trgm). Phân trang. `selectinload` tránh N+1. |
| M2 | B9 | Thêm, xóa nhân viên trong bộ phận | Basic | `GET /manager/candidates`, `POST /manager/departments/{id}/members`, `DELETE /manager/departments/{id}/members/{user_id}` | Chỉ thêm user role User chưa thuộc bộ phận nào. Xóa chỉ gỡ liên kết. Idempotent. |
| M3 | B10 | Quản lý báo cáo của nhân viên | Basic | `GET /manager/reports`, `GET /manager/reports/{id}` | Bộ lọc động (tên, khoảng ngày, bộ phận), phân trang, sắp xếp. Index (department_id, report_date). Ngoài phạm vi trả 404. |
| M4 | B11 | Quản lý nhân viên | Basic | `GET /manager/employees`, `GET /manager/employees/{id}` | Tìm theo tên, email, chỉ trong bộ phận mình. Schema không có trường nhạy cảm. |
| M5 | B13 | Export Excel báo cáo theo ngày | Advance | `GET /manager/reports/export?date=` | openpyxl write-only, `StreamingResponse`. Đánh dấu người chưa nộp. |

### Admin

| Mã | Ô Excel | Chức năng | Mức | Endpoint / Trigger | Kỹ thuật áp dụng |
| --- | --- | --- | --- | --- | --- |
| A1 | B15 | Quản lý user (CRUD) | Basic | `GET/POST /admin/users`, `GET/PATCH/DELETE /admin/users/{id}` | Email unique, xóa mềm, lọc theo role và bộ phận. Tạo user thì kích hoạt S2. Khóa, xóa user thì tăng `token_version`. |
| A2 | B16 | Quản lý bộ phận (CRUD) | Basic | `GET/POST /admin/departments`, `GET/PATCH/DELETE /admin/departments/{id}` | Mã bộ phận unique, xóa mềm, không xóa bộ phận còn thành viên. |
| A3 | B17 | Thêm, xóa manager cho bộ phận | Basic | `GET /admin/departments/{id}/members`, `POST /admin/departments/{id}/managers`, `DELETE /admin/departments/{id}/managers/{user_id}` | Bảng nhiều–nhiều `department_managers`. Chỉ gán user role Manager. |
| A4 | B19 | Import nhân viên từ Excel | Advance | `GET /admin/users/import-template`, `POST /admin/users/import` | Tối đa 2 MB, 1.000 dòng. Validate toàn bộ bằng Pydantic, có lỗi thì không ghi gì và trả lỗi theo dòng. Gửi mail S2 sau commit. |

### System

| Mã | Ô Excel | Chức năng | Mức | Trigger | Kỹ thuật áp dụng |
| --- | --- | --- | --- | --- | --- |
| S1 | B21 | Email cho manager khi nhân viên tạo báo cáo | Basic | Sau `POST /me/reports` | Celery task, Jinja2, smtplib, retry tối đa 3 lần, ghi `email_logs`. |
| S2 | B22 | Email cho user khi admin tạo tài khoản | Basic | Sau `POST /admin/users` hoặc import · `POST /auth/setup-password` | Link đặt mật khẩu dùng 1 lần, token lưu dạng hash, hết hạn 24 giờ. |
| S3 | B24 | Email thống kê cuối tháng theo bộ phận | Advance | Celery Beat, 08:00 ngày 1 hằng tháng | GROUP BY bộ phận, nhân viên; so với số ngày làm việc. Chạy lại không gửi trùng. |

## 2. Bổ sung để hệ thống dùng được

File yêu cầu không ghi nhưng cần có:

- Nhân viên xem lại báo cáo của mình; API trả danh sách người nhận hợp lệ.
- Danh sách ứng viên để manager thêm vào bộ phận.
- Admin xem thành viên bộ phận trước khi gán manager.
- Đặt mật khẩu lần đầu từ link trong email (đi kèm S2).
- Làm mới token, health check, file Excel mẫu để import.
- Theo yêu cầu kỹ thuật của trainer: upload ảnh đại diện (xử lý file, lưu local/S3), CLI tạo admin và seed dữ liệu mẫu (Typer), debug bằng debugpy. Xem `docs/progress/10-day-plan.md`.

## 3. Ngoài phạm vi

- Sửa báo cáo trong ngày (khoảng 4 giờ, xem Q5).
- Quên mật khẩu qua email (khoảng 5 giờ).
- Deploy lên server thật, domain, dịch vụ mail production.
- Thông báo trong ứng dụng, audit log chi tiết.
- Frontend, ứng dụng mobile.

## 4. Câu hỏi cần PM chốt

Hạn chốt: cuối Ngày 2. Chưa chốt thì làm theo đề xuất mặc định.

| # | Câu hỏi | Đề xuất mặc định | Ảnh hưởng |
| --- | --- | --- | --- |
| Q1 | Một nhân viên thuộc một hay nhiều bộ phận? | Một bộ phận (`users.department_id`). Nếu nhiều, đổi sang bảng liên kết. | Ngày 3, 5 |
| Q2 | Một bộ phận có nhiều manager? Một manager quản lý nhiều bộ phận? | Có cả hai. | Ngày 3, 5 |
| Q3 | Ai phải viết báo cáo? | Chỉ role User. | Ngày 4, 8 |
| Q4 | Người nhận báo cáo chọn từ đâu? | Manager của bộ phận người viết, mặc định chọn tất cả. | Ngày 4 |
| Q5 | Báo cáo đã gửi có được sửa, xóa? | Không. | Ngày 4 |
| Q6 | Được tạo báo cáo cho ngày nào? | Hôm nay và tối đa 3 ngày trước, không cho tương lai. | Ngày 4, 8 |
| Q7 | Manager thêm nhân viên từ đâu? Xem nhân viên trong phạm vi nào? | Thêm từ user role User chưa thuộc bộ phận nào. Chỉ xem nhân viên bộ phận mình. | Ngày 5 |
| Q8 | Khi admin tạo tài khoản, mật khẩu do ai đặt? | User tự đặt qua link dùng 1 lần, hết hạn 24 giờ. | Ngày 3, 6 |
| Q9 | Xóa user, bộ phận là xóa hẳn hay xóa mềm? | Xóa mềm; không xóa bộ phận còn thành viên. | Ngày 3 |
| Q10 | File import có format bắt buộc? Một dòng lỗi thì sao? | File mẫu: email, họ tên, số điện thoại, ngày sinh, mã bộ phận, role. Có lỗi thì không ghi gì. | Ngày 7 |
| Q11 | File export gồm những gì? | Một ngày, các bộ phận trong phạm vi. Cột: nhân viên, trạng thái nộp, 4 nội dung, giờ gửi. | Ngày 7 |
| Q12 | Thống kê tháng: ngày làm việc, giờ gửi, người nhận? | Thứ 2 đến thứ 6, chưa trừ lễ. 08:00 ngày 1 tháng sau, gửi manager từng bộ phận. | Ngày 8 |
| Q13 | Có gồm frontend và deploy server thật? | Không. Chỉ API, Swagger, Docker Compose. | Ngày 9, 10 |

## 5. Giả định chung

- Múi giờ nghiệp vụ: Asia/Ho_Chi_Minh. DB lưu UTC.
- Role hệ thống: `USER`, `MANAGER`, `ADMIN`. Một user có đúng một role.
- Ngôn ngữ thông báo lỗi và email: tiếng Việt.
