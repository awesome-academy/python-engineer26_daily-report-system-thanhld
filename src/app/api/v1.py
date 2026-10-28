"""Gom router của các module dưới tiền tố /api/v1 (Settings.api_v1_prefix).

Router được thêm dần theo kế hoạch trong docs/progress/10-day-plan.md:
/auth và /me (Ngày 1, 3), /admin (Ngày 4), /me/reports (Ngày 5), /manager (Ngày 6).
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.modules.auth.router import router as auth_router
from app.modules.users.models import UserRole
from app.modules.users.router import me_router

# Nhóm theo role: kiểm tra role một lần ở nhóm, endpoint bên trong không tự kiểm tra lại.
# Router của module phải include vào nhóm trước khi nhóm được include vào api_router,
# vì include_router chép route tại thời điểm gọi.
_ROLE_ERRORS = error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
admin_router = APIRouter(
    prefix="/admin", dependencies=[Depends(require_roles(UserRole.ADMIN))], responses=_ROLE_ERRORS
)
manager_router = APIRouter(
    prefix="/manager",
    dependencies=[Depends(require_roles(UserRole.MANAGER))],
    responses=_ROLE_ERRORS,
)

api_router = APIRouter(prefix=get_settings().api_v1_prefix)
api_router.include_router(auth_router)
api_router.include_router(me_router)
api_router.include_router(admin_router)
api_router.include_router(manager_router)
