from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DbSession
from app.modules.auth.schemas import TokenResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Xác thực"])


@router.post(
    "/login",
    summary="Đăng nhập, lấy access token",
    description=(
        "Chuẩn OAuth2 password flow: gửi form `username` (là email) và `password`. "
        "Trên Swagger, bấm **Authorize** để đăng nhập và tự gắn token cho các request sau."
    ),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession
) -> TokenResponse:
    return await AuthService(session).login(form.username, form.password)
