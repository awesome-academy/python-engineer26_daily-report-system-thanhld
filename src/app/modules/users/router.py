from fastapi import APIRouter, status

from app.api.deps import CurrentTokenClaims, CurrentUser, IdPath
from app.core.constants import LOGIN_ATTEMPT_WINDOW_MINUTES, LOGIN_MAX_FAILED_ATTEMPTS
from app.core.exceptions import error_responses
from app.core.pagination import Page
from app.modules.auth.dependencies import AuthServiceDep
from app.modules.auth.schemas import TokenResponse
from app.modules.users.dependencies import UserServiceDep
from app.modules.users.schemas import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    PasswordChange,
    UserListQuery,
    UserOut,
    UserProfileUpdate,
)

me_router = APIRouter(prefix="/me", tags=["Cá nhân"])
# Include vào admin_router (api/v1.py): role ADMIN được kiểm tra ở nhóm, endpoint không tự kiểm tra.
admin_users_router = APIRouter(prefix="/users", tags=["Admin: người dùng"])


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


@admin_users_router.get(
    "",
    summary="Danh sách user",
    description=(
        "Chỉ user chưa bị xóa, sắp theo id. `keyword` tìm trong họ tên (không phân biệt dấu, "
        'hoa thường: "nguyen" khớp "Nguyễn") hoặc email.'
    ),
    responses=error_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_users(params: UserListQuery, user_service: UserServiceDep) -> Page[AdminUserOut]:
    users, total = await user_service.list_users(params)
    return Page.build([AdminUserOut.model_validate(u) for u in users], total=total, params=params)


@admin_users_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Tạo user",
    description=(
        "Không nhận mật khẩu: user tự đặt mật khẩu qua link gửi email, chưa đăng nhập được đến "
        "lúc đó. Email không phân biệt hoa thường, trùng với user chưa bị xóa thì nhận 409."
    ),
    responses=error_responses(
        status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT
    ),
)
async def create_user(data: AdminUserCreate, user_service: UserServiceDep) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.create_by_admin(data))


@admin_users_router.get(
    "/{user_id}",
    summary="Xem user",
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def get_user(user_id: IdPath, user_service: UserServiceDep) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.get_user(user_id))


@admin_users_router.patch(
    "/{user_id}",
    summary="Sửa user, gán bộ phận, khóa tài khoản",
    description=(
        "Cập nhật từng phần. `department_id: null` gỡ user khỏi bộ phận. `is_active: false` khóa "
        "tài khoản, mọi phiên đăng nhập hết hiệu lực ngay. Không tự khóa, tự đổi role của mình "
        "(400). Không đổi role của manager đang quản lý bộ phận (409)."
    ),
    responses=error_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def update_user(
    user_id: IdPath, data: AdminUserUpdate, admin: CurrentUser, user_service: UserServiceDep
) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.update_by_admin(admin, user_id, data))


@admin_users_router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa user",
    description=(
        "Xóa mềm, mọi phiên đăng nhập hết hiệu lực ngay; báo cáo của user vẫn giữ. Không tự xóa "
        "mình (400). Manager đang quản lý bộ phận phải được gỡ khỏi bộ phận trước (409)."
    ),
    responses=error_responses(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def delete_user(user_id: IdPath, admin: CurrentUser, user_service: UserServiceDep) -> None:
    await user_service.delete_by_admin(admin, user_id)
