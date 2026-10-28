from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.core.exceptions import error_responses
from app.modules.users.dependencies import UserServiceDep
from app.modules.users.schemas import UserOut, UserProfileUpdate

me_router = APIRouter(prefix="/me", tags=["Cá nhân"])


@me_router.get(
    "",
    summary="Xem thông tin tài khoản đang đăng nhập",
    responses=error_responses(status.HTTP_401_UNAUTHORIZED),
)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@me_router.patch(
    "",
    summary="Sửa hồ sơ cá nhân",
    description=(
        "Cập nhật từng phần: field không gửi thì giữ nguyên, gửi `null` để xóa số điện thoại, "
        "ngày sinh. Không đổi được email, role: gửi các field này nhận 422."
    ),
    responses=error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def update_me(
    data: UserProfileUpdate, user: CurrentUser, user_service: UserServiceDep
) -> UserOut:
    return UserOut.model_validate(await user_service.update_profile(user, data))
