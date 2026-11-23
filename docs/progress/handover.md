# Tổng kết bàn giao

Bàn giao ngày 22/11/2026, cuối Ngày 10 của [kế hoạch 10 ngày](10-day-plan.md). Mọi issue, pull request theo dõi trên GitHub Project của repo.

## Đã làm

### Chức năng: 15/15

| Mã | Chức năng | Issue | Pull request |
| --- | --- | --- | --- |
| U1 | Đăng nhập, refresh token, đăng xuất, khóa tạm khi sai nhiều lần | #4, #8 | #35, #39 |
| U2 | Xem, sửa hồ sơ, đổi mật khẩu, ảnh đại diện (lưu local hoặc S3) | #10, #24 | #41, #57, #58 |
| U3 | Tạo báo cáo hằng ngày, lịch sử và chi tiết báo cáo của tôi | #14, #15 | #46, #47 |
| M1 | Bộ phận tôi quản lý, thành viên | #17 | #50 |
| M2 | Thêm, gỡ nhân viên trong bộ phận | #18 | #51 |
| M3 | Báo cáo của nhân viên: lọc, sắp xếp, chi tiết | #20 | #53 |
| M4 | Nhân viên của tôi | #19 | #52 |
| M5 | Export Excel báo cáo theo ngày | #25 | #59 |
| A1 | Quản lý user | #12 | #49 |
| A2 | Quản lý bộ phận | #11 | #42 |
| A3 | Gán, gỡ manager cho bộ phận | #13 | #44 |
| A4 | Import nhân viên từ Excel | #26 | #62 |
| S1 | Email cho manager khi có báo cáo mới (Celery, Redis) | #21, #22 | #54, #55 |
| S2 | Email link đặt mật khẩu khi admin tạo tài khoản | #23 | #56 |
| S3 | Email thống kê tháng (Celery Beat) | #27 | #60, #64 |

### Nền tảng, chất lượng

| Việc | Issue | Pull request |
| --- | --- | --- |
| Khởi tạo project: Docker Compose, Alembic, Swagger, test, CI | #2 | #33 |
| Thiết kế database (draw.io), models, migration | #3, #5 | #34, #36 |
| CLI Typer (tạo admin, seed), debug bằng debugpy | #6, #7 | #37, #38 |
| Phân quyền theo role (`require_roles`), phạm vi bộ phận cho manager | #9, #16 | #40, #48 |
| Test end-to-end các luồng chính | #28 | #63 |
| Rà soát hiệu năng: N+1, index, phân trang | #29 | #65 |
| Rà soát bảo mật theo OWASP API Top 10 | #30 | #66 |
| README, ví dụ trên Swagger, Postman collection | #31 | #68, #67 |
| Đăng nhập với ký tự NUL trả 422 thay vì 500 (lỗi 1 của UAT) | #45 | #69 |
| Kịch bản demo, UAT, sửa lỗi 2, 3, tổng kết này | #32 | #70 |

Chất lượng lúc bàn giao:

- Hơn 1.200 test chạy trên PostgreSQL, Redis thật (unit, DB, API, e2e), coverage trên 99%; CI chạy ruff, mypy strict, pytest trên mỗi pull request, coverage dưới 80% thì đỏ.
- Có test riêng cho những chỗ dễ sai: ma trận quyền theo bộ phận với hai bộ phận có manager riêng, kiểm kê phân quyền mọi endpoint lấy từ route thật, số câu SQL của mọi danh sách, hai transaction chạy đồng thời, mốc giờ theo giờ Việt Nam.

## UAT ngày 22/11/2026

Chạy trên stack Docker đầy đủ (API, worker, beat, PostgreSQL 17, Redis 7, Mailpit) dựng từ code cuối cùng: `master` (đã gồm #66, #68, #67) cùng #69, #70; dữ liệu `seed --reset`.

| Cách thử | Kết quả |
| --- | --- |
| Đi hết kịch bản demo bản đầy đủ lúc đó (11 cảnh, 107 bước) theo từng vai: mã HTTP, mã lỗi, email trên Mailpit, nội dung file Excel | Lần đầu lệch 2 bước (lỗi 2, 3 bên dưới); sau khi sửa đạt 107/107 |
| Postman collection gọi mọi endpoint | 48 request, 97 kiểm tra đạt |
| Gửi dữ liệu lạ tới mọi endpoint, sinh từ OpenAPI: từng tham số path, query, từng field JSON, form, file, header `Authorization`. Ký tự NUL, surrogate, chuỗi 1 MB, số ngoài phạm vi bigint, JSON lồng 100.000 tầng, JSON hỏng, file giả, tên file lạ | 3.875 request; lỗi 500 chỉ ở đăng nhập (lỗi 1), không request nào chậm quá 3 giây. Sau khi sửa: không còn lỗi 5xx |

Lỗi phát hiện và đã sửa (mức cao: sai hoặc lộ dữ liệu, sai quyền, chặn luồng chính; trung bình: lỗi 500 với dữ liệu lạ, dữ liệu sai quy tắc; thấp: lệch tài liệu, trải nghiệm):

| # | Lỗi | Mức | Cách sửa |
| --- | --- | --- | --- |
| 1 | `POST /auth/login` với `username` chứa ký tự NUL trả 500: chuỗi đi thẳng xuống PostgreSQL (#45) | Trung bình | #69: form đăng nhập chặn NUL và chuỗi dài hơn giới hạn lúc tạo tài khoản như mọi input khác, trả 422 trước khi tra DB |
| 2 | Seed tạo tài khoản hôm nay nhưng báo cáo mẫu cho 5 ngày trước, trái quy tắc "không báo cáo cho ngày trước khi có tài khoản": tài khoản mẫu không báo cáo bù được, thống kê tháng (S3) không tính các báo cáo đó nên không demo được | Trung bình | Cùng tài liệu này: tài khoản mẫu có từ ngày đầu tháng trước, báo cáo mẫu các ngày làm việc từ đó đến hôm qua (mỗi nhân viên bỏ trống khoảng 1/5 số ngày); tài khoản có sẵn không nhận báo cáo trước ngày tạo |
| 3 | `GET /me` không trả bộ phận như `docs/api-design.md` mô tả | Thấp | Cùng tài liệu này: hồ sơ `/me` có `department` (`id`, `code`, `name`) |

Không còn lỗi mức cao đã biết.

## Việc còn lại, giới hạn đã biết

Ngoài phạm vi đã thống nhất ([requirements](../requirements.md), mục 3 và Q13): sửa báo cáo sau khi gửi, quên mật khẩu qua email, frontend, deploy lên server thật, thông báo trong ứng dụng.

Giới hạn của bản hiện tại:

| Giới hạn | Ảnh hưởng | Hướng xử lý |
| --- | --- | --- |
| Ngày làm việc là thứ 2 đến thứ 6, chưa trừ ngày lễ (Q12) | Thống kê tháng tính ngày lễ là ngày phải nộp | Bảng ngày nghỉ do admin quản lý, dùng trong `is_working_day` (`core/workdays.py`) |
| Không lưu lịch sử thành viên bộ phận | Export ngày cũ tính "chưa nộp" theo thành viên hiện tại; thống kê tháng tính người chuyển bộ phận giữa tháng ở bộ phận mới | Bảng lịch sử thành viên (từ ngày, đến ngày) |
| Thống kê tháng tính lúc 08:00 ngày 1 | Báo cáo bù cho ngày cuối tháng nộp sau thời điểm đó không có trong email (email có ghi thời điểm tính) | Lùi giờ gửi, hoặc gửi bản cập nhật ở lượt ngày 3 |
| Import Excel đồng bộ, tối đa 1.000 dòng | File lớn hơn phải chia nhỏ | Job nền Celery kèm trạng thái import |
| Khóa tạm đăng nhập theo email; chưa giới hạn số request theo IP | Người khác có thể cố ý khóa một tài khoản 15 phút | Rate limit theo IP ở reverse proxy ([security.md](../security.md), mục Khi triển khai production) |
| Ví dụ trên Swagger không hiện field `null` (FastAPI bỏ khi xuất OpenAPI) | Người đọc phải xem tab Schema để biết field nào nhận `null` | Chấp nhận |

Khi triển khai thật (chưa làm): đặt `ENVIRONMENT=production` (log JSON, chặn seed), `JWT_SECRET_KEY` ngẫu nhiên riêng, SMTP thật, `FRONTEND_URL`, `STORAGE_BACKEND=s3` với bucket private; reverse proxy HTTPS kèm rate limit, header bảo mật; sao lưu PostgreSQL. Biến cấu hình ở `.env.example`, việc cần làm về bảo mật ở [security.md](../security.md), mục Khi triển khai production.

## Tài liệu

| Tài liệu | Dùng khi |
| --- | --- |
| [README](../../README.md) | Chạy project, lệnh hay dùng, thử API, xử lý lỗi thường gặp |
| [requirements.md](../requirements.md) | Chức năng, quyết định nghiệp vụ Q1–Q13 |
| [architecture.md](../architecture.md) | Công nghệ, cấu trúc module, quyết định kỹ thuật |
| [database.md](../database.md) | Bảng, ràng buộc, index, số đo hiệu năng |
| [api-design.md](../api-design.md) | Quy ước, mã lỗi, hành vi chi tiết của từng endpoint |
| [demo.md](../demo.md) | Kịch bản demo theo vai, câu hỏi thường gặp |
| [security.md](../security.md) | Checklist OWASP API Top 10, rủi ro chấp nhận, việc khi triển khai |
| [postman/](../postman/) | Gọi thử mọi endpoint |
