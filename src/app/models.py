"""Gom model của mọi module.

Import file này ở mọi điểm vào (app, CLI, Alembic, test) để SQLAlchemy biết đủ các class khi
nối quan hệ khai báo bằng tên (ví dụ `relationship("Department")`), và để Alembic autogenerate
nhìn thấy đủ bảng. Khi thêm module có model, import model đó tại đây.
"""

from app.core.database import Base
from app.modules.auth.models import RefreshToken, UserToken
from app.modules.departments.models import Department, DepartmentManager
from app.modules.notifications.models import EmailLog
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User

__all__ = [
    "Base",
    "DailyReport",
    "Department",
    "DepartmentManager",
    "EmailLog",
    "RefreshToken",
    "ReportRecipient",
    "User",
    "UserToken",
]
