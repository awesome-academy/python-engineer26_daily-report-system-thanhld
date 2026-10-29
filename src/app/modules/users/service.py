from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.departments.exceptions import DepartmentNotFoundError
from app.modules.departments.repository import DepartmentRepository
from app.modules.users.exceptions import (
    CannotModifyOwnAccountError,
    EmailAlreadyExistsError,
    UserManagesDepartmentsError,
    UserNotFoundError,
)
from app.modules.users.models import USER_EMAIL_UNIQUE_INDEX, User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    UserCreate,
    UserListParams,
    UserProfileUpdate,
)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.departments = DepartmentRepository(session)

    async def create_user(self, data: UserCreate) -> User:
        await self._ensure_email_available(data.email)
        user = User(
            email=data.email,
            full_name=data.full_name,
            role=data.role,
            password_hash=await hash_password(data.password),
        )
        await self._save_new(user)
        return user

    async def update_profile(self, user: User, data: UserProfileUpdate) -> User:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.session.commit()
        return user

    async def list_users(self, params: UserListParams) -> tuple[Sequence[User], int]:
        return await self.users.search(
            params, keyword=params.keyword, role=params.role, department_id=params.department_id
        )

    async def get_user(self, user_id: int) -> User:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        return user

    async def create_by_admin(self, data: AdminUserCreate) -> User:
        """Tạo tài khoản chưa có mật khẩu: chưa đăng nhập được đến khi user đặt mật khẩu (S2)."""
        await self._ensure_email_available(data.email)
        if data.department_id is not None:
            await self._ensure_department_exists(data.department_id)
        user = User(**data.model_dump())
        await self._save_new(user)
        return user

    async def update_by_admin(self, admin: User, user_id: int, data: AdminUserUpdate) -> User:
        changes = data.model_dump(exclude_unset=True)
        # Khóa dòng: đổi role, khóa tài khoản không chạy xen với một lần sửa khác của cùng user.
        user = await self.users.get_by_id_for_update(user_id)
        try:
            if user is None:
                raise UserNotFoundError
            await self._check_admin_update(admin, user, changes)
        except AppError:
            await self.session.rollback()
            raise

        if user.is_active and changes.get("is_active") is False:
            # Khóa tài khoản: mọi access token, refresh token đã cấp hết hiệu lực ngay.
            user.token_version += 1
        for field, value in changes.items():
            setattr(user, field, value)
        await commit_unique(self.session, USER_EMAIL_UNIQUE_INDEX, EmailAlreadyExistsError())
        return user

    async def delete_by_admin(self, admin: User, user_id: int) -> None:
        """Xóa mềm, thu hồi mọi phiên. Báo cáo của user vẫn giữ để tra cứu, thống kê."""
        user = await self.users.get_by_id_for_update(user_id)
        try:
            if user is None:
                raise UserNotFoundError
            if user.id == admin.id:
                raise CannotModifyOwnAccountError
            if await self.departments.has_managed_department(user.id):
                raise UserManagesDepartmentsError
        except AppError:
            await self.session.rollback()
            raise

        user.deleted_at = datetime.now(UTC)
        # Tăng token_version thay vì ghi revoked_at cho refresh token: refresh token đã thu hồi
        # mà bị gửi lại thì bị coi là token lộ, log cảnh báo sai sự thật.
        user.token_version += 1
        await self.session.commit()

    async def _check_admin_update(self, admin: User, user: User, changes: dict[str, Any]) -> None:
        role_changed = "role" in changes and changes["role"] is not user.role
        locking = user.is_active and changes.get("is_active") is False
        if user.id == admin.id:
            if role_changed:
                raise CannotModifyOwnAccountError("role")
            if locking:
                raise CannotModifyOwnAccountError("is_active")
        # Manager bị hạ role hay bị khóa thì bộ phận còn liên kết tới người không làm manager được
        # nữa (A3 cũng không cho gán user bị khóa làm manager).
        demoting_manager = role_changed and user.role is UserRole.MANAGER
        if (demoting_manager or locking) and await self.departments.has_managed_department(user.id):
            raise UserManagesDepartmentsError
        if changes.get("department_id") is not None:
            await self._ensure_department_exists(changes["department_id"])
        if "email" in changes:
            existing = await self.users.get_by_email(changes["email"])
            if existing is not None and existing.id != user.id:
                raise EmailAlreadyExistsError

    async def _ensure_email_available(self, email: str) -> None:
        if await self.users.get_by_email(email) is not None:
            raise EmailAlreadyExistsError

    async def _ensure_department_exists(self, department_id: int) -> None:
        if await self.departments.get_by_id(department_id) is None:
            raise DepartmentNotFoundError

    async def _save_new(self, user: User) -> None:
        self.users.add(user)
        # Hai request tạo cùng email chạy song song đều qua được bước kiểm tra email ở trên.
        await commit_unique(self.session, USER_EMAIL_UNIQUE_INDEX, EmailAlreadyExistsError())
