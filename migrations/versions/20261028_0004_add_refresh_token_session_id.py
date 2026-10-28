"""Thêm refresh_tokens.session_id: mã phiên đăng nhập, giữ nguyên qua các lần refresh.

Đăng xuất thu hồi mọi refresh token cùng session_id. Dòng có sẵn (mỗi dòng là một lần đăng nhập
chưa refresh) lấy session_id bằng jti.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("session_id", sa.String(length=64), nullable=True))
    op.execute("UPDATE refresh_tokens SET session_id = jti")
    op.alter_column("refresh_tokens", "session_id", nullable=False)
    op.create_index(
        op.f("ix_refresh_tokens_session_id"), "refresh_tokens", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_session_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
