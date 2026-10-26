"""Hằng số dùng chung toàn project. Tránh lặp số và chuỗi cố định ở nhiều nơi."""

from enum import StrEnum


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


# Phân trang
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Health check
HEALTH_CHECK_TIMEOUT_SECONDS = 3

# Độ dài cột: model dùng cho String(n), schema dùng cho min_length, max_length để luôn khớp nhau.
# Migration vẫn ghi số trực tiếp vì migration là bản chụp schema tại thời điểm tạo.
EMAIL_MAX_LENGTH = 255
PASSWORD_HASH_MAX_LENGTH = 255
FULL_NAME_MIN_LENGTH = 1
FULL_NAME_MAX_LENGTH = 100
PHONE_MAX_LENGTH = 20

# JWT. HS256 cần khóa tối thiểu 256 bit (RFC 7518, mục 3.2).
ACCESS_TOKEN_EXPIRE_MINUTES = 15
JWT_SECRET_MIN_LENGTH = 32

# Mật khẩu người dùng nhập
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
DEPARTMENT_CODE_MAX_LENGTH = 20
DEPARTMENT_NAME_MAX_LENGTH = 100
# Đường dẫn file trong kho lưu trữ (local hoặc S3), ví dụ ảnh đại diện.
STORAGE_KEY_MAX_LENGTH = 255
TOKEN_JTI_MAX_LENGTH = 64
# SHA-256 dạng hex.
TOKEN_HASH_LENGTH = 64
TOKEN_PURPOSE_MAX_LENGTH = 32
EMAIL_TEMPLATE_MAX_LENGTH = 64
EMAIL_DEDUP_KEY_MAX_LENGTH = 128
EMAIL_STATUS_MAX_LENGTH = 16
