"""Tạo bảng users cho API đăng nhập (bước B4).

Cột department_id, avatar_key thêm ở migration 0003 khi có bảng departments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column(
            "role",
            sa.Enum("USER", "MANAGER", "ADMIN", name="user_role"),
            server_default="USER",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "ix_users_full_name_search",
        "users",
        [sa.literal_column("immutable_unaccent(lower(full_name))").label("full_name_search")],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"full_name_search": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_users_email_active",
        "users",
        [sa.literal_column("lower(email)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_users_email_active", table_name="users", postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.drop_index(
        "ix_users_full_name_search",
        table_name="users",
        postgresql_using="gin",
        postgresql_ops={"full_name_search": "gin_trgm_ops"},
    )
    op.drop_table("users")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
