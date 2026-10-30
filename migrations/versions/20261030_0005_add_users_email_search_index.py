"""Thêm GIN trigram cho lower(email): tìm một phần email trong danh sách user của admin.

Điều kiện tìm kiếm "tên LIKE ... OR email LIKE ..." chỉ dùng được index khi cả hai vế đều có
index; trước đây vế email không có nên cả câu thành Seq Scan.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_users_email_search",
        "users",
        [sa.literal_column("lower(email)").label("email_search")],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"email_search": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_users_email_search",
        table_name="users",
        postgresql_using="gin",
        postgresql_ops={"email_search": "gin_trgm_ops"},
    )
