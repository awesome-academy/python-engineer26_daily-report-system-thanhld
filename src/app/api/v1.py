"""Gom router của các module dưới tiền tố /api/v1.

Router được thêm dần theo kế hoạch trong docs/progress/10-day-plan.md:
/auth và /me (Ngày 2), /admin (Ngày 3), /me/reports (Ngày 4), /manager (Ngày 5).
"""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
