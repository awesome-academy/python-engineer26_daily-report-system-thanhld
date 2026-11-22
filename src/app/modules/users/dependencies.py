from typing import Annotated

from fastapi import Depends, File, Query, UploadFile

from app.api.deps import CurrentUser, DbSession, Storage
from app.core.constants import (
    AVATAR_IMAGE_TYPES,
    AVATAR_MAX_BYTES,
    AVATAR_MAX_MB,
    AVATAR_TYPES_LABEL,
    USER_IMPORT_MAX_BYTES,
    USER_IMPORT_MAX_MB,
    USER_IMPORT_MAX_ROWS,
)
from app.core.uploads import UploadedImage, read_image, read_upload
from app.modules.departments.dependencies import DepartmentServiceDep
from app.modules.users.schemas import EmployeeListParams
from app.modules.users.service import AvatarService, UserImportService, UserService


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_user_import_service(session: DbSession) -> UserImportService:
    return UserImportService(session)


UserImportServiceDep = Annotated[UserImportService, Depends(get_user_import_service)]


async def get_user_import_file(
    file: Annotated[
        UploadFile,
        File(
            description=f"File .xlsx theo mẫu, tối đa {USER_IMPORT_MAX_MB} MB, "
            f"{USER_IMPORT_MAX_ROWS} dòng"
        ),
    ],
) -> bytes:
    return await read_upload(file, USER_IMPORT_MAX_BYTES)


# Nội dung file import đã kiểm tra dung lượng (413). Loại file (415) xét lúc đọc file.
UserImportFile = Annotated[bytes, Depends(get_user_import_file)]


def get_avatar_service(session: DbSession, storage: Storage) -> AvatarService:
    return AvatarService(session, storage)


AvatarServiceDep = Annotated[AvatarService, Depends(get_avatar_service)]


async def get_avatar_image(
    file: Annotated[
        UploadFile,
        File(description=f"Ảnh {AVATAR_TYPES_LABEL}, tối đa {AVATAR_MAX_MB} MB"),
    ],
) -> UploadedImage:
    return await read_image(file, AVATAR_MAX_BYTES, AVATAR_IMAGE_TYPES)


# Ảnh đại diện đã kiểm tra dung lượng (413) và loại ảnh theo nội dung (415).
AvatarImage = Annotated[UploadedImage, Depends(get_avatar_image)]


async def get_employee_list_params(
    params: Annotated[EmployeeListParams, Query()],
    manager: CurrentUser,
    departments: DepartmentServiceDep,
) -> EmployeeListParams:
    """Bộ lọc `department_id` phải là bộ phận manager quản lý, như `ManagedDepartment` trên path.

    Nhận cả bộ query chứ không riêng `department_id`: FastAPI gọi dependency trước khi validate
    query của endpoint, tách riêng thì `page` sai kèm bộ phận ngoài phạm vi trả 404 thay vì 422.
    """
    if params.department_id is not None:
        await departments.get_managed_department(manager.id, params.department_id)
    return params


# Query của danh sách nhân viên, đã kiểm tra phạm vi của `department_id`: router nhận alias này
# như các danh sách khác nhận `...ListQuery`, không nhận thẳng `Query()`.
EmployeeListQuery = Annotated[EmployeeListParams, Depends(get_employee_list_params)]
