from fastapi import APIRouter, status

from app.api.deps import CurrentTokenClaims, CurrentUser
from app.core.constants import LOGIN_ATTEMPT_WINDOW_MINUTES, LOGIN_MAX_FAILED_ATTEMPTS
from app.core.exceptions import error_responses
from app.modules.auth.dependencies import AuthServiceDep
from app.modules.auth.schemas import TokenResponse
from app.modules.users.dependencies import UserServiceDep
from app.modules.users.schemas import PasswordChange, UserOut, UserProfileUpdate

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


@me_router.put(
    "/password",
    summary="Đổi mật khẩu",
    description=(
        "Cần mật khẩu hiện tại. Mật khẩu mới có chữ thường, chữ hoa, chữ số và ký tự đặc biệt. "
        "Đổi xong thì mọi phiên đăng nhập khác hết hiệu lực; response trả cặp token mới cho "
        "phiên hiện tại. Sai mật khẩu hiện tại được đếm chung với đăng nhập sai: quá "
        f"{LOGIN_MAX_FAILED_ATTEMPTS} lần trong {LOGIN_ATTEMPT_WINDOW_MINUTES} phút thì nhận 429."
    ),
    responses=error_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_429_TOO_MANY_REQUESTS,
    ),
)
async def change_my_password(
    data: PasswordChange,
    user: CurrentUser,
    claims: CurrentTokenClaims,
    auth_service: AuthServiceDep,
) -> TokenResponse:
    return await auth_service.change_password(user, claims.session_id, data)
