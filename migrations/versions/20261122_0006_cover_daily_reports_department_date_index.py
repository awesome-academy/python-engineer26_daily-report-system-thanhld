"""Thêm author_id, id vào index (department_id, report_date) của daily_reports (INCLUDE).

Danh sách báo cáo của manager (M3) đếm và sắp mọi báo cáo trong phạm vi rồi mới cắt trang. Index
cũ chỉ có bộ phận và ngày, nên phải đọc dòng báo cáo để lấy người viết (JOIN users): bộ phận
95 người, một năm khoảng 25.000 lần đọc ngẫu nhiên. Có thêm author_id, id thì đếm và chọn id
của trang chỉ đọc index (Index Only Scan).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_daily_reports_department_date"
TABLE = "daily_reports"


def upgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX, TABLE, ["department_id", "report_date"], postgresql_include=["author_id", "id"]
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(INDEX, TABLE, ["department_id", "report_date"])
