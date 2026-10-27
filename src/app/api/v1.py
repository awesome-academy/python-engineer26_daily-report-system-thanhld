"""Gom router của các module dưới tiền tố /api/v1.

Router được thêm dần theo kế hoạch trong docs/progress/10-day-plan.md:
/auth và /me (Ngày 1, 3), /admin (Ngày 4), /me/reports (Ngày 5), /manager (Ngày 6).
"""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
