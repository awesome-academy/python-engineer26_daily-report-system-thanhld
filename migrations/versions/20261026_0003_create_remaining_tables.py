"""Tạo các bảng còn lại theo thiết kế database (bước B5).

Thêm departments, department_managers, daily_reports, report_recipients, refresh_tokens,
user_tokens, email_logs và cột users.department_id, users.avatar_key. ON DELETE, index, CHECK
theo docs/database.md.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
    )
    op.create_index(
        "uq_departments_code_active",
        "departments",
        [sa.literal_column("lower(code)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "email_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("dedup_key", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "SENT",
                "FAILED",
                name="email_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_logs")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_email_logs_dedup_key")),
    )
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("planned_work", sa.Text(), nullable=False),
        sa.Column("actual_work", sa.Text(), nullable=False),
        sa.Column("incomplete_reason", sa.Text(), nullable=True),
        sa.Column("next_day_plan", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_daily_reports_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_daily_reports_department_id_departments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_reports")),
        sa.UniqueConstraint("author_id", "report_date", name="uq_daily_reports_author_date"),
    )
    op.create_index(
        "ix_daily_reports_department_date",
        "daily_reports",
        ["department_id", "report_date"],
        unique=False,
    )
    op.create_table(
        "department_managers",
        sa.Column("department_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_department_managers_department_id_departments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_department_managers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("department_id", "user_id", name=op.f("pk_department_managers")),
    )
    op.create_index(
        op.f("ix_department_managers_user_id"), "department_managers", ["user_id"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("jti", name=op.f("uq_refresh_tokens_jti")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "SETUP_PASSWORD",
                name="user_token_purpose",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_tokens_token_hash")),
    )
    op.create_index(op.f("ix_user_tokens_user_id"), "user_tokens", ["user_id"], unique=False)
    op.create_table(
        "report_recipients",
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name=op.f("fk_report_recipients_recipient_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_reports.id"],
            name=op.f("fk_report_recipients_report_id_daily_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", "recipient_id", name=op.f("pk_report_recipients")),
    )
    op.create_index(
        op.f("ix_report_recipients_recipient_id"),
        "report_recipients",
        ["recipient_id"],
        unique=False,
    )
    op.add_column("users", sa.Column("department_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("avatar_key", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_users_department_id"), "users", ["department_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_users_department_id_departments"),
        "users",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_users_department_id_departments"), "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_department_id"), table_name="users")
    op.drop_column("users", "avatar_key")
    op.drop_column("users", "department_id")
    op.drop_index(op.f("ix_report_recipients_recipient_id"), table_name="report_recipients")
    op.drop_table("report_recipients")
    op.drop_index(op.f("ix_user_tokens_user_id"), table_name="user_tokens")
    op.drop_table("user_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_department_managers_user_id"), table_name="department_managers")
    op.drop_table("department_managers")
    op.drop_index("ix_daily_reports_department_date", table_name="daily_reports")
    op.drop_table("daily_reports")
    op.drop_table("email_logs")
    op.drop_index(
        "uq_departments_code_active",
        table_name="departments",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("departments")
