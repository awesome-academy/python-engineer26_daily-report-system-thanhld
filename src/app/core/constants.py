"""Hằng số dùng chung toàn project. Tránh lặp số và chuỗi cố định ở nhiều nơi."""

from enum import StrEnum


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    """Nơi lưu file người dùng tải lên (ảnh đại diện), chọn bằng cấu hình STORAGE_BACKEND."""

    LOCAL = "local"
    S3 = "s3"


class ImageType(StrEnum):
    """Loại ảnh nhận diện được từ nội dung file; giá trị là MIME type lưu kèm file."""

    JPEG = "image/jpeg"
    PNG = "image/png"


# Phân trang
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# OFFSET = (page - 1) * page_size phải nằm trong bigint, nếu không PostgreSQL báo lỗi (500).
# Một triệu trang, mỗi trang 100 bản ghi, vẫn dư xa so với dữ liệu thật.
MAX_PAGE = 1_000_000
# Từ khóa tìm kiếm trong danh sách
KEYWORD_MAX_LENGTH = 100
# Ký tự escape trong LIKE: từ khóa "50%" phải tìm đúng chuỗi "50%", không phải "50" + bất kỳ.
LIKE_ESCAPE_CHAR = "\\"

# Health check
HEALTH_CHECK_TIMEOUT_SECONDS = 3

# Kết nối PostgreSQL, Redis: service treo thì báo lỗi sau chừng này giây, không chờ vô hạn.
DB_CONNECT_TIMEOUT_SECONDS = 5
REDIS_TIMEOUT_SECONDS = 2

# Khóa chính bigint identity: id client gửi lên (path, query, body) ngoài khoảng này thì trả 422,
# không gửi xuống DB (xem Id ở core/validators.py).
ID_MIN = 1
BIGINT_MAX = 2**63 - 1

# Độ dài cột: model dùng cho String(n), schema dùng cho min_length, max_length để luôn khớp nhau.
# Migration vẫn ghi số trực tiếp vì migration là bản chụp schema tại thời điểm tạo.
EMAIL_MAX_LENGTH = 255
PASSWORD_HASH_MAX_LENGTH = 255
FULL_NAME_MIN_LENGTH = 1
FULL_NAME_MAX_LENGTH = 100
PHONE_MAX_LENGTH = 20
# Số điện thoại: chỉ chữ số, có thể có dấu + đầu, từ 9 đến 15 chữ số (E.164 tối đa 15).
PHONE_PATTERN = r"^\+?[0-9]{9,15}$"
DEPARTMENT_CODE_MIN_LENGTH = 1
DEPARTMENT_CODE_MAX_LENGTH = 20
# Mã bộ phận chỉ gồm chữ cái không dấu (ASCII), chữ số, gạch ngang, gạch dưới để dùng được
# trong file import Excel và URL; lưu chữ hoa.
DEPARTMENT_CODE_PATTERN = r"^[A-Za-z0-9_-]+$"
DEPARTMENT_NAME_MIN_LENGTH = 1
DEPARTMENT_NAME_MAX_LENGTH = 100
# Cột description là text, giới hạn ở schema để request không gửi nội dung quá dài.
DEPARTMENT_DESCRIPTION_MAX_LENGTH = 1000
# Nội dung báo cáo: cột text, giới hạn ở schema để request không gửi nội dung quá dài.
REPORT_CONTENT_MIN_LENGTH = 1
REPORT_CONTENT_MAX_LENGTH = 5000
# Đường dẫn file trong kho lưu trữ (local hoặc S3), ví dụ ảnh đại diện.
STORAGE_KEY_MAX_LENGTH = 255
TOKEN_JTI_MAX_LENGTH = 64
SESSION_ID_MAX_LENGTH = 64
# SHA-256 dạng hex.
TOKEN_HASH_LENGTH = 64
TOKEN_PURPOSE_MAX_LENGTH = 32
EMAIL_TEMPLATE_MAX_LENGTH = 64
EMAIL_DEDUP_KEY_MAX_LENGTH = 128
EMAIL_STATUS_MAX_LENGTH = 16

# Báo cáo hằng ngày: được tạo cho hôm nay và tối đa ngần này ngày trước, không cho ngày tương lai.
REPORT_BACKDATE_DAYS = 3
# Số người nhận client chọn trong một request. Tối đa: manager của một bộ phận chỉ vài người, chặn
# danh sách id quá dài gửi xuống truy vấn.
REPORT_RECIPIENTS_MIN = 1
REPORT_RECIPIENTS_MAX = 50
# Số user manager thêm vào bộ phận trong một request: tối đa bằng một trang danh sách ứng viên.
DEPARTMENT_MEMBERS_ADD_MIN = 1
DEPARTMENT_MEMBERS_ADD_MAX = MAX_PAGE_SIZE

# JWT. HS256 cần khóa tối thiểu 256 bit (RFC 7518, mục 3.2).
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
# Refresh token vừa bị thu hồi mà được gửi lại trong khoảng này (client timeout rồi gửi lại,
# hai tab cùng refresh) thì chỉ từ chối, không coi là token bị lộ.
REFRESH_TOKEN_REUSE_GRACE_SECONDS = 30
JWT_SECRET_MIN_LENGTH = 32
# Refresh token client gửi lên trong body. JWT của project dài khoảng 300 ký tự.
JWT_MAX_LENGTH = 1024

# Link đặt mật khẩu lần đầu gửi qua email (S2): token ngẫu nhiên 32 byte (256 bit), hết hạn sau
# SETUP_PASSWORD_TOKEN_EXPIRE_HOURS giờ. Token gửi lên dài 43 ký tự (base64url); giới hạn rộng hơn
# chút để chặn chuỗi quá dài trước khi băm.
ONE_TIME_TOKEN_BYTES = 32
ONE_TIME_TOKEN_MAX_LENGTH = 128
ONE_TIME_TOKEN_PATTERN = r"^[A-Za-z0-9_-]+$"  # noqa: S105 (ký tự của base64url, không phải mật khẩu)
SETUP_PASSWORD_TOKEN_EXPIRE_HOURS = 24
# Trang đặt mật khẩu của frontend, ghép sau FRONTEND_URL.
SETUP_PASSWORD_PATH = "/setup-password"  # noqa: S105 (đường dẫn, không phải mật khẩu)

# Khóa tạm đăng nhập: quá số lần thử trong cửa sổ thời gian thì trả 429 đến khi hết cửa sổ.
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15

# Tiền tố key trên Redis
REDIS_REVOKED_SESSION_PREFIX = "auth:revoked-session:"
REDIS_LOGIN_ATTEMPTS_PREFIX = "auth:login-attempts:"

# Mật khẩu người dùng nhập
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Lưu trữ file. Backend local: API phục vụ file đã lưu tại đường dẫn này (StaticFiles).
LOCAL_STORAGE_URL_PATH = "/media"
# Backend S3: bucket private, URL trả cho client là URL ký sẵn, hết hạn sau chừng này giây.
S3_PRESIGNED_URL_EXPIRE_SECONDS = 60 * 60
# S3 treo thì request upload báo lỗi sau chừng này giây, không chờ vô hạn. Số lần thử gồm lần đầu.
S3_CONNECT_TIMEOUT_SECONDS = 5
S3_READ_TIMEOUT_SECONDS = 10
S3_MAX_ATTEMPTS = 3

# Ảnh đại diện: JPEG hoặc PNG, tối đa AVATAR_MAX_MB. Loại ảnh xét bằng các byte đầu của nội dung
# (magic bytes), không tin Content-Type hay đuôi tên file client gửi.
BYTES_PER_MB = 1024 * 1024
AVATAR_MAX_MB = 2
AVATAR_MAX_BYTES = AVATAR_MAX_MB * BYTES_PER_MB
AVATAR_IMAGE_TYPES = (ImageType.JPEG, ImageType.PNG)
# "JPEG hoặc PNG": mô tả trên Swagger lấy từ AVATAR_IMAGE_TYPES, không ghi lại danh sách loại ảnh.
AVATAR_TYPES_LABEL = " hoặc ".join(image_type.name for image_type in AVATAR_IMAGE_TYPES)
IMAGE_SIGNATURES = {
    ImageType.JPEG: b"\xff\xd8\xff",
    ImageType.PNG: b"\x89PNG\r\n\x1a\n",
}
IMAGE_EXTENSIONS = {ImageType.JPEG: "jpg", ImageType.PNG: "png"}
# Key của ảnh đại diện: avatars/{user_id}/{chuỗi ngẫu nhiên}.{đuôi}. Mỗi lần đổi ảnh một key mới,
# URL cũ không trả nhầm ảnh mới từ cache của trình duyệt, CDN.
AVATAR_KEY_PREFIX = "avatars"

# Celery task gặp lỗi tạm thời (SMTP, mất kết nối) thì thử lại tối đa TASK_MAX_RETRIES lần, lần
# thứ n chờ TASK_RETRY_BACKOFF_SECONDS * 2**n giây (30s, 60s, 120s). Mọi task dùng chung.
TASK_MAX_RETRIES = 3
TASK_RETRY_BACKOFF_SECONDS = 30
SMTP_TIMEOUT_SECONDS = 10
# Cột email_logs.error là text: chỉ giữ đoạn đầu của thông báo lỗi.
EMAIL_ERROR_MAX_LENGTH = 1000
# Ngày hiển thị trong email (ngày báo cáo).
EMAIL_DATE_FORMAT = "%d/%m/%Y"
