import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.constants import IMAGE_SIGNATURES, ImageType
from app.core.exceptions import UnauthorizedError
from app.core.storage import FileStorage, StorageError
from app.core.uploads import UploadedImage
from app.modules.users import service as users_service
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.service import AvatarService
from tests.factories import create_user
from tests.helpers import capture_module_logs

IMAGE = UploadedImage(data=IMAGE_SIGNATURES[ImageType.PNG] + b"anh", type=ImageType.PNG)
OLD_KEY = "avatars/0/anh-cu.png"


class MemoryStorage(FileStorage):
    """Kho lưu trong bộ nhớ, để kiểm tra service ghi, xóa đúng file mà không chạm đĩa."""

    def __init__(self, *, fail_delete: bool = False, barrier: asyncio.Barrier | None = None):
        self.files: dict[str, bytes] = {}
        self.fail_delete = fail_delete
        # Cho các lần lưu cùng chờ nhau: mọi request cùng đi tới bước khóa dòng một lúc.
        self.barrier = barrier

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = data
        if self.barrier is not None:
            await self.barrier.wait()

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            msg = "S3 không phản hồi"
            raise StorageError(msg)
        self.files.pop(key, None)

    def url(self, key: str) -> str:
        return f"memory://{key}"


async def user_with_old_avatar(session: AsyncSession, storage: MemoryStorage) -> User:
    user = await create_user(session)
    user.avatar_key = OLD_KEY
    storage.files[OLD_KEY] = b"anh-cu"
    await session.flush()
    return user


async def test_update_avatar_saves_new_file_and_deletes_old(db_session: AsyncSession) -> None:
    storage = MemoryStorage()
    user = await user_with_old_avatar(db_session, storage)

    updated = await AvatarService(db_session, storage).update(user, IMAGE)

    assert updated.avatar_key is not None
    assert storage.files == {updated.avatar_key: IMAGE.data}


async def test_failed_commit_removes_new_file_and_keeps_old(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage()
    user = await user_with_old_avatar(db_session, storage)

    async def fail_commit() -> None:
        raise OperationalError("COMMIT", {}, Exception("mất kết nối"))

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(OperationalError):
        await AvatarService(db_session, storage).update(user, IMAGE)

    # DB không đổi nên ảnh cũ phải còn; ảnh mới không ai trỏ tới thì bị dọn.
    assert storage.files == {OLD_KEY: b"anh-cu"}


async def test_failed_old_file_delete_still_updates_avatar(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage(fail_delete=True)
    user = await user_with_old_avatar(db_session, storage)
    logs = capture_module_logs(monkeypatch, users_service)

    updated = await AvatarService(db_session, storage).update(user, IMAGE)

    # DB đã trỏ sang ảnh mới: xóa ảnh cũ lỗi chỉ để lại file thừa, request vẫn thành công.
    assert updated.avatar_key != OLD_KEY
    assert set(storage.files) == {OLD_KEY, updated.avatar_key}
    assert [(log["event"], log["log_level"], log["key"]) for log in logs] == [
        ("avatar_delete_failed", "warning", OLD_KEY)
    ]


async def test_user_deleted_during_upload_gets_401_and_new_file_removed(
    db_session: AsyncSession,
) -> None:
    storage = MemoryStorage()
    user = await create_user(db_session)
    user.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(UnauthorizedError):
        await AvatarService(db_session, storage).update(user, IMAGE)

    assert storage.files == {}


async def test_concurrent_avatar_updates_leave_only_current_file(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = await create_user(setup)
        await setup.commit()
    storage = MemoryStorage(barrier=asyncio.Barrier(2))
    try:
        async with AsyncSession(engine) as one, AsyncSession(engine) as two:
            # Mỗi request đã nạp user (như CurrentUser) khi chưa có ảnh, rồi cùng đổi ảnh.
            first = await UserRepository(one).get_by_id(user.id)
            second = await UserRepository(two).get_by_id(user.id)
            assert first is not None
            assert second is not None
            await asyncio.gather(
                AvatarService(one, storage).update(first, IMAGE),
                AvatarService(two, storage).update(second, IMAGE),
            )

        async with AsyncSession(engine) as check:
            current = await UserRepository(check).get_by_id(user.id)
        # Request chạy sau chờ khóa, thấy ảnh của request trước và xóa nó: không còn file thừa.
        assert current is not None
        assert list(storage.files) == [current.avatar_key]
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user.id))
