"""Hằng số dùng chung toàn project. Tránh lặp số và chuỗi cố định ở nhiều nơi."""

from enum import StrEnum


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


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
# Số người nhận tối đa trong một request: manager của một bộ phận chỉ vài người, chặn danh sách id
# quá dài gửi xuống truy vấn.
REPORT_RECIPIENTS_MAX = 50

# JWT. HS256 cần khóa tối thiểu 256 bit (RFC 7518, mục 3.2).
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
# Refresh token vừa bị thu hồi mà được gửi lại trong khoảng này (client timeout rồi gửi lại,
# hai tab cùng refresh) thì chỉ từ chối, không coi là token bị lộ.
REFRESH_TOKEN_REUSE_GRACE_SECONDS = 30
JWT_SECRET_MIN_LENGTH = 32
# Refresh token client gửi lên trong body. JWT của project dài khoảng 300 ký tự.
JWT_MAX_LENGTH = 1024

# Khóa tạm đăng nhập: quá số lần thử trong cửa sổ thời gian thì trả 429 đến khi hết cửa sổ.
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15

# Tiền tố key trên Redis
REDIS_REVOKED_SESSION_PREFIX = "auth:revoked-session:"
REDIS_LOGIN_ATTEMPTS_PREFIX = "auth:login-attempts:"

# Mật khẩu người dùng nhập
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
