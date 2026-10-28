from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentTokenClaims, CurrentUser
from app.core.constants import LOGIN_ATTEMPT_WINDOW_MINUTES, LOGIN_MAX_FAILED_ATTEMPTS
from app.core.exceptions import error_responses
from app.modules.auth.dependencies import AuthServiceDep
from app.modules.auth.schemas import RefreshTokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Xác thực"])


@router.post(
    "/login",
    summary="Đăng nhập, lấy access token và refresh token",
    description=(
        "Chuẩn OAuth2 password flow: gửi form `username` (là email) và `password`. "
        "Trên Swagger, bấm **Authorize** để đăng nhập và tự gắn token cho các request sau. "
        f"Thử quá {LOGIN_MAX_FAILED_ATTEMPTS} lần trong {LOGIN_ATTEMPT_WINDOW_MINUTES} phút "
        "thì bị khóa tạm (429) đến hết khoảng thời gian đó."
    ),
    responses=error_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_429_TOO_MANY_REQUESTS,
    ),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], auth_service: AuthServiceDep
) -> TokenResponse:
    return await auth_service.login(form.username, form.password)


@router.post(
    "/refresh",
    summary="Lấy cặp token mới bằng refresh token",
    description=(
        "Refresh token chỉ dùng được một lần. Gửi lại refresh token đã dùng thì mọi phiên "
        "đăng nhập của tài khoản bị thu hồi, phải đăng nhập lại."
    ),
    responses=error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def refresh(data: RefreshTokenRequest, auth_service: AuthServiceDep) -> TokenResponse:
    return await auth_service.refresh(data.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Đăng xuất",
    description="Thu hồi phiên đăng nhập hiện tại: cả access token và refresh token đi kèm.",
    responses=error_responses(status.HTTP_401_UNAUTHORIZED),
)
async def logout(_: CurrentUser, claims: CurrentTokenClaims, auth_service: AuthServiceDep) -> None:
    await auth_service.logout(claims)
