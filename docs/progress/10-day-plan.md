# Kế hoạch 10 ngày

Dự án: Daily Report API · Repo: https://github.com/awesome-academy/python-engineer26_daily-report-system-thanhld

Kế hoạch đi theo các bước trong hướng dẫn Mock Project của trainer (bỏ qua B1 vì đã chọn đề tài):

- **B2:** tạo ticket, quản lý trên GitHub Projects.
- **B3:** thiết kế database bằng draw.io, self review, gửi mentor review.
- **B4:** init project, API đăng nhập JWT, Swagger, Alembic.
- **B5:** models, relationship, migration cho toàn bộ bảng.
- **B6:** implement chức năng theo thứ tự ưu tiên.

Mỗi ticket là một GitHub issue, theo dõi trên GitHub Project của dự án (trường **Ngày** và **Status**). Mỗi pull request đóng một hoặc vài issue.

## Lịch theo ngày

| Ngày | Bước | Nội dung | Chức năng |
| --- | --- | --- | --- |
| 1 | B2, B3, B4 | Ticket và GitHub Project; thiết kế DB bằng draw.io; init project (Docker, Alembic, Swagger, test, CI); API đăng nhập JWT; CLI tạo admin | — |
| 2 | B5 | Models, relationship, migration cho toàn bộ bảng; seeder dữ liệu mẫu bằng Typer; debug bằng debugpy | — |
| 3 | B6 | Đăng nhập đầy đủ: refresh token, đăng xuất, giới hạn đăng nhập sai; RBAC qua `Depends`; hồ sơ cá nhân, đổi mật khẩu | U1, U2 |
| 4 | B6 | Admin: CRUD bộ phận, CRUD user, gán và gỡ manager | A1, A2, A3 |
| 5 | B6 | Báo cáo hằng ngày; policy phạm vi bộ phận cho manager | U3 |
| 6 | B6 | Chức năng Manager: bộ phận, thành viên, nhân viên, báo cáo | M1, M2, M3, M4 |
| 7 | B6 | Celery và Redis; email khi có báo cáo mới, email khi tạo tài khoản. **MVP: đủ 12 chức năng Basic** | S1, S2 |
| 8 | B6 | Xử lý file: lưu trữ local/S3, upload ảnh đại diện, export Excel (streaming), import Excel | M5, A4 |
| 9 | B6 | Email thống kê cuối tháng (Celery Beat); test end-to-end; rà soát hiệu năng. **Đủ 15 chức năng** | S3 |
| 10 | — | Rà soát bảo mật, hoàn thiện tài liệu, demo, sửa lỗi. **Bàn giao** | — |

## Đáp ứng yêu cầu kỹ thuật của trainer

| Yêu cầu | Áp dụng trong dự án | Ngày |
| --- | --- | --- |
| Unit test, e2e test (pytest, pytest-asyncio, httpx AsyncClient) | Test trên PostgreSQL thật, rollback sau mỗi test; e2e cho các luồng chính | 1, 9 |
| Xử lý file (UploadFile, streaming, lưu trữ local/S3) | Upload ảnh đại diện và import Excel bằng `UploadFile`; export Excel bằng `StreamingResponse`; lớp lưu trữ đổi được giữa local và S3 | 8 |
| Gửi mail (Celery + Redis), lập lịch (Celery Beat) | Email S1, S2 qua Celery; thống kê tháng S3 bằng Celery Beat | 7, 9 |
| Phân quyền (OAuth2 + JWT, RBAC qua Depends) | `OAuth2PasswordBearer`, JWT; `require_roles` và policy phạm vi bộ phận qua `Depends` | 1, 3, 5 |
| Performance (async/await, N+1, pagination, index) | SQLAlchemy async; `selectinload`; `paginate()` dùng chung; index theo truy vấn | 1–9 |
| Debug (debugpy, logging) | structlog kèm request-id; debugpy trong Docker, cấu hình attach của VS Code | 1, 2 |
| Seeder với CLI (Typer hoặc Click) | Typer: `create-admin`, `seed` | 1, 2 |

## Mốc cần PM, mentor

- **Ngày 1:** mentor review thiết kế database (PR thiết kế DB).
- **Cuối Ngày 2:** PM chốt 13 câu hỏi trong `docs/requirements.md`. Ngày 4 làm phần bộ phận, phụ thuộc Q1, Q2, Q8, Q9.
- **Ngày 7:** demo MVP.
- **Ngày 10:** demo bàn giao.

## Mẫu báo cáo hằng ngày

```
1/ Total effort: 7h
2/ Actual:
Mock project: <link pull request>
3/ Next plan:
<link issue của ngày tiếp theo>
```
