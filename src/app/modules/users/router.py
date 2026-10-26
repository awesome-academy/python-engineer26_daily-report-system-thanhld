from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.core.exceptions import error_responses
from app.modules.users.schemas import UserOut

me_router = APIRouter(prefix="/me", tags=["Cá nhân"])


@me_router.get(
    "",
    summary="Xem thông tin tài khoản đang đăng nhập",
    responses=error_responses(status.HTTP_401_UNAUTHORIZED),
)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
