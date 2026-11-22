"""Dữ liệu mẫu: lệnh `daily-report seed` tạo ra, ví dụ trên Swagger dùng lại.

Tách khỏi `app.cli.seed` để schema của các module import được mà không vòng lại CLI. Seed vào DB
trống thì id theo đúng thứ tự trong `DEPARTMENTS`, `USERS` (`seed_id`), nên ví dụ trên Swagger
dùng id này để "Try it out" chạy được ngay sau khi seed.
"""

from dataclasses import dataclass

from app.modules.users.models import UserRole


@dataclass(frozen=True)
class SeedDepartment:
    code: str
    name: str
    description: str


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: UserRole
    department_code: str | None


DEPARTMENTS = (
    SeedDepartment("DEV", "Phòng Phát triển", "Phát triển sản phẩm"),
    SeedDepartment("QA", "Phòng Kiểm thử", "Kiểm thử và đảm bảo chất lượng"),
    SeedDepartment("HR", "Phòng Nhân sự", "Tuyển dụng và đào tạo"),
)

# Nguồn duy nhất: manager của bộ phận suy ra từ user role MANAGER có department_code tương ứng.
USERS = (
    SeedUser("admin@example.com", "Quản trị viên", UserRole.ADMIN, None),
    SeedUser("manager.dev@example.com", "Trần Minh Quân", UserRole.MANAGER, "DEV"),
    SeedUser("manager.qa@example.com", "Lê Thu Hà", UserRole.MANAGER, "QA"),
    SeedUser("manager.hr@example.com", "Phạm Ngọc Lan", UserRole.MANAGER, "HR"),
    SeedUser("an.nguyen@example.com", "Nguyễn Văn An", UserRole.USER, "DEV"),
    SeedUser("binh.tran@example.com", "Trần Thị Bình", UserRole.USER, "DEV"),
    SeedUser("cuong.le@example.com", "Lê Quốc Cường", UserRole.USER, "QA"),
    SeedUser("dung.pham@example.com", "Phạm Thùy Dung", UserRole.USER, "QA"),
    SeedUser("giang.vo@example.com", "Võ Hoàng Giang", UserRole.USER, "HR"),
)

# (việc dự định, việc thực tế đã làm, lý do chưa hoàn thành, việc ngày tiếp theo)
SAMPLE_WORK = (
    ("Làm API đăng nhập", "Xong API đăng nhập, viết test", None, "Làm API hồ sơ cá nhân"),
    (
        "Làm API hồ sơ cá nhân",
        "Xong xem, sửa hồ sơ",
        "Đổi mật khẩu chờ chốt quy tắc",
        "Đổi mật khẩu",
    ),
    ("Viết test phân quyền", "Xong test cho nhóm /admin", None, "Test cho nhóm /manager"),
    (
        "Sửa lỗi sau review",
        "Sửa 3/4 góp ý",
        "Một góp ý cần hỏi lại mentor",
        "Hoàn thành góp ý còn lại",
    ),
    ("Tối ưu truy vấn báo cáo", "Thêm index, bỏ N+1", None, "Export Excel báo cáo"),
)


def seed_id(record: SeedDepartment | SeedUser) -> int:
    """Id của bản ghi khi seed vào DB trống: seed thêm bản ghi theo thứ tự của tuple."""
    if isinstance(record, SeedDepartment):
        return DEPARTMENTS.index(record) + 1
    return USERS.index(record) + 1


# Bản ghi dùng trong ví dụ, hướng dẫn: nhân viên, bộ phận của nhân viên đó, manager bộ phận đó.
EXAMPLE_ADMIN = next(u for u in USERS if u.role is UserRole.ADMIN)
EXAMPLE_EMPLOYEE = next(u for u in USERS if u.role is UserRole.USER)
EXAMPLE_DEPARTMENT = next(d for d in DEPARTMENTS if d.code == EXAMPLE_EMPLOYEE.department_code)
EXAMPLE_MANAGER = next(
    u for u in USERS if u.role is UserRole.MANAGER and u.department_code == EXAMPLE_DEPARTMENT.code
)
# Tài khoản admin tạo sau khi seed (A1, A4), nhận id kế tiếp.
EXAMPLE_NEW_USER = SeedUser(
    "hoa.do@example.com", "Đỗ Thị Hoa", UserRole.USER, EXAMPLE_DEPARTMENT.code
)
EXAMPLE_NEW_USER_ID = len(USERS) + 1
# Báo cáo ví dụ: đủ mọi trường (lý do chưa hoàn thành khác None, vì Swagger không hiện `null`).
EXAMPLE_WORK = next(work for work in SAMPLE_WORK if work[2] is not None)
# Mật khẩu trong hướng dẫn (README, Swagger, Postman). Seed không lấy làm mặc định: vẫn bắt nhập.
EXAMPLE_PASSWORD = "Matkhau@123"  # noqa: S105 (mật khẩu ví dụ của tài liệu)
