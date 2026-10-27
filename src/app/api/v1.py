"""Gom router của các module dưới tiền tố /api/v1 (Settings.api_v1_prefix).

Router được thêm dần theo kế hoạch trong docs/progress/10-day-plan.md:
/auth và /me (Ngày 1, 3), /admin (Ngày 4), /me/reports (Ngày 5), /manager (Ngày 6).
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.auth.router import router as auth_router
from app.modules.users.router import me_router

api_router = APIRouter(prefix=get_settings().api_v1_prefix)
api_router.include_router(auth_router)
api_router.include_router(me_router)
