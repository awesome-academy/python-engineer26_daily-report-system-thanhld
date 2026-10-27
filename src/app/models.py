"""Gom model của mọi module để Alembic autogenerate nhìn thấy đủ bảng.

Khi thêm module có model, import model đó tại đây.
"""

from app.core.database import Base
from app.modules.users.models import User

__all__ = ["Base", "User"]
