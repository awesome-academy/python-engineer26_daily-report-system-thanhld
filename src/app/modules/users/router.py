from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.modules.users.schemas import UserOut

me_router = APIRouter(prefix="/me", tags=["Cá nhân"])


@me_router.get("", summary="Xem thông tin tài khoản đang đăng nhập")
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
