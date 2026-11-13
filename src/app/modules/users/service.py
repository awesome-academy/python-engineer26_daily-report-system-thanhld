from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.auth.models import UserTokenPurpose
from app.modules.auth.repository import UserTokenRepository
from app.modules.auth.tasks import send_account_setup_email
from app.modules.departments.exceptions import DepartmentNotFoundError
from app.modules.departments.repository import DepartmentRepository
from app.modules.users.exceptions import (
    CannotModifyOwnAccountError,
    EmailAlreadyExistsError,
    LastActiveAdminError,
    UserManagesDepartmentsError,
    UserNotFoundError,
)
from app.modules.users.models import USER_EMAIL_UNIQUE_INDEX, User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    EmployeeListParams,
    UserCreate,
    UserListParams,
    UserProfileUpdate,
)
from app.worker import enqueue_task


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.departments = DepartmentRepository(session)
        self.user_tokens = UserTokenRepository(session)

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

    async def list_employees(
        self, manager_id: int, params: EmployeeListParams
    ) -> tuple[Sequence[User], int]:
        """Nhân viên (role USER) các bộ phận manager quản lý.

        `params.department_id` ngoài phạm vi đã bị chặn (404) ở dependency `EmployeeListQuery`;
        câu truy vấn vẫn luôn lọc theo phạm vi, không trông vào bước đó.
        """
        return await self.users.search_employees(
            self.departments.managed_department_ids(manager_id), params
        )

    async def get_employee(self, manager_id: int, user_id: int) -> User:
        """Nhân viên ngoài phạm vi trả đúng lỗi của user không tồn tại, không dò được id."""
        user = await self.users.get_employee(
            user_id, self.departments.managed_department_ids(manager_id)
        )
        if user is None:
            raise UserNotFoundError
        return user

    async def create_by_admin(self, data: AdminUserCreate) -> User:
        """Tạo tài khoản chưa có mật khẩu, gửi email link đặt mật khẩu (S2).

        Chưa đăng nhập được đến khi user tự đặt mật khẩu qua link.
        """
        await self._ensure_email_available(data.email)
        if data.department_id is not None:
            await self._ensure_department_exists(data.department_id)
        user = User(**data.model_dump())
        await self._save_new(user)
        # Sau commit: worker đọc được user vừa tạo.
        await enqueue_task(send_account_setup_email, user.id)
        return user

    async def update_by_admin(self, admin: User, user_id: int, data: AdminUserUpdate) -> User:
        changes = data.model_dump(exclude_unset=True)
        # Khóa, đổi role có thể gỡ quyền của một admin: khóa tập admin trước khi khóa user đích.
        may_remove_admin = changes.get("is_active") is False or "role" in changes
        admin_ids = await self.users.lock_active_admin_ids() if may_remove_admin else []
        # Khóa dòng: đổi role, khóa tài khoản không chạy xen với một lần sửa khác của cùng user.
        user = await self.users.get_by_id_for_update(user_id)
        try:
            if user is None:
                raise UserNotFoundError
            await self._check_admin_update(admin, user, changes, admin_ids)
        except AppError:
            await self.session.rollback()
            raise

        if user.is_active and changes.get("is_active") is False:
            # Khóa tài khoản: mọi access token, refresh token đã cấp hết hiệu lực ngay.
            user.token_version += 1
        # User chưa đặt mật khẩu (S2): link đã gửi tới email cũ (admin gõ nhầm) hoặc cấp trước khi
        # bị khóa thì hủy ngay, không đợi lúc dùng mới chặn (mở khóa lại không làm link cũ sống
        # lại). Còn hoạt động thì gửi link mới tới email hiện tại sau commit.
        setup_link_outdated = user.password_hash is None and any(
            field in changes and changes[field] != getattr(user, field)
            for field in ("email", "is_active")
        )
        for field, value in changes.items():
            setattr(user, field, value)
        if setup_link_outdated:
            await self.user_tokens.delete_for_user(user.id, UserTokenPurpose.SETUP_PASSWORD)
        await commit_unique(self.session, USER_EMAIL_UNIQUE_INDEX, EmailAlreadyExistsError())
        if setup_link_outdated and user.is_active:
            await enqueue_task(send_account_setup_email, user.id)
        return user

    async def delete_by_admin(self, admin: User, user_id: int) -> None:
        """Xóa mềm, thu hồi mọi phiên. Báo cáo của user vẫn giữ để tra cứu, thống kê."""
        # Chưa biết user đích có phải admin không, nên luôn khóa tập admin trước (số admin ít).
        admin_ids = await self.users.lock_active_admin_ids()
        user = await self.users.get_by_id_for_update(user_id)
        try:
            if user is None:
                raise UserNotFoundError
            if user.id == admin.id:
                raise CannotModifyOwnAccountError
            self._ensure_other_active_admin(user, admin_ids)
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

    async def _check_admin_update(
        self, admin: User, user: User, changes: dict[str, Any], admin_ids: list[int]
    ) -> None:
        role_changed = "role" in changes and changes["role"] is not user.role
        locking = user.is_active and changes.get("is_active") is False
        if user.id == admin.id:
            if role_changed:
                raise CannotModifyOwnAccountError("role")
            if locking:
                raise CannotModifyOwnAccountError("is_active")
        if role_changed or locking:
            self._ensure_other_active_admin(user, admin_ids)
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

    @staticmethod
    def _ensure_other_active_admin(user: User, admin_ids: list[int]) -> None:
        # Chặn tự gỡ quyền mình chưa đủ: hai admin gỡ quyền nhau cùng lúc thì không còn ai.
        # admin_ids đã khóa nên request chạy sau đếm theo kết quả của request trước.
        if user.id in admin_ids and len(admin_ids) == 1:
            raise LastActiveAdminError

    async def _ensure_email_available(self, email: str) -> None:
        if await self.users.get_by_email(email) is not None:
            raise EmailAlreadyExistsError

    async def _ensure_department_exists(self, department_id: int) -> None:
        # Khóa FOR SHARE đến khi commit: lệnh xóa bộ phận chạy cùng lúc phải chờ rồi mới đếm thành
        # viên (thấy user vừa gán, trả 409); xóa xong trước thì ở đây không thấy bộ phận (404).
        if await self.departments.get_by_id_for_share(department_id) is None:
            raise DepartmentNotFoundError

    async def _save_new(self, user: User) -> None:
        self.users.add(user)
        # Hai request tạo cùng email chạy song song đều qua được bước kiểm tra email ở trên.
        await commit_unique(self.session, USER_EMAIL_UNIQUE_INDEX, EmailAlreadyExistsError())
