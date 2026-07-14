from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models.file import File, FileStatus
from app.models.folder import DEFAULT_FOLDER_ID, DEFAULT_FOLDER_NAME, Folder


class FolderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_default_folder(self) -> Folder:
        folder = await self.session.get(Folder, DEFAULT_FOLDER_ID)
        if folder is not None:
            return folder

        folder = Folder(
            id=DEFAULT_FOLDER_ID,
            name=DEFAULT_FOLDER_NAME,
            parent_id=None,
            sort_order=0,
        )
        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def get(self, folder_id: str | None) -> Folder:
        if folder_id is None:
            return await self.ensure_default_folder()

        folder = await self.session.get(Folder, folder_id)
        if folder is None:
            raise AppError(
                "Folder not found",
                code=ErrorCode.FOLDER_NOT_FOUND,
                status_code=404,
            )
        return folder

    async def list(self) -> tuple[list[Folder], dict[str, int]]:
        await self.ensure_default_folder()
        rows = await self.session.scalars(
            select(Folder).order_by(Folder.sort_order.asc(), Folder.created_at.asc())
        )
        folders = list(rows)
        counts_result = await self.session.execute(
            select(File.folder_id, func.count(File.id))
            .where(File.index_status != FileStatus.DELETED.value)
            .group_by(File.folder_id)
        )
        counts = {
            folder_id or DEFAULT_FOLDER_ID: int(count)
            for folder_id, count in counts_result.all()
        }
        return folders, counts

    async def create(self, *, name: str, parent_id: str | None = None) -> Folder:
        clean_name = name.strip()
        if not clean_name:
            raise AppError(
                "Folder name is required",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        if parent_id is not None:
            await self.get(parent_id)
        await self._ensure_unique_name(clean_name, parent_id=parent_id)

        max_sort = await self.session.scalar(select(func.max(Folder.sort_order)))
        folder = Folder(
            id=f"fld_{uuid4().hex}",
            name=clean_name,
            parent_id=parent_id,
            sort_order=int(max_sort or 0) + 1,
        )
        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def update(
        self,
        folder_id: str,
        *,
        name: str | None = None,
        parent_id: str | None = None,
        update_parent: bool = False,
        sort_order: int | None = None,
    ) -> Folder:
        folder = await self.get(folder_id)
        if folder.id == DEFAULT_FOLDER_ID and update_parent:
            raise AppError(
                "Default folder cannot be nested",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise AppError(
                    "Folder name is required",
                    code=ErrorCode.VALIDATION_ERROR,
                    status_code=422,
                )
            await self._ensure_unique_name(
                clean_name,
                parent_id=folder.parent_id,
                exclude_folder_id=folder.id,
            )
            folder.name = clean_name
        if update_parent:
            if parent_id == folder.id:
                raise AppError(
                    "Folder cannot be its own parent",
                    code=ErrorCode.VALIDATION_ERROR,
                    status_code=409,
                )
            if parent_id is not None:
                await self.get(parent_id)
                await self._ensure_not_descendant(folder.id, parent_id)
            await self._ensure_unique_name(
                folder.name,
                parent_id=parent_id,
                exclude_folder_id=folder.id,
            )
            folder.parent_id = parent_id
        if sort_order is not None:
            folder.sort_order = sort_order

        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def delete(self, folder_id: str) -> None:
        folder = await self.get(folder_id)
        if folder.id == DEFAULT_FOLDER_ID:
            raise AppError(
                "Default folder cannot be deleted",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )

        file_count = await self.session.scalar(
            select(func.count(File.id))
            .where(File.folder_id == folder.id)
            .where(File.index_status != FileStatus.DELETED.value)
        )
        child_count = await self.session.scalar(
            select(func.count(Folder.id)).where(Folder.parent_id == folder.id)
        )
        if int(file_count or 0) > 0 or int(child_count or 0) > 0:
            raise AppError(
                "Only empty folders can be deleted",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )

        await self.session.delete(folder)
        await self.session.commit()

    async def _ensure_unique_name(
        self,
        name: str,
        *,
        parent_id: str | None,
        exclude_folder_id: str | None = None,
    ) -> None:
        stmt = select(Folder.id).where(
            func.lower(Folder.name) == name.lower(),
            Folder.parent_id.is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id,
        )
        if exclude_folder_id is not None:
            stmt = stmt.where(Folder.id != exclude_folder_id)
        existing = await self.session.scalar(stmt.limit(1))
        if existing is not None:
            raise AppError(
                "A folder with the same name already exists in this folder",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )

    async def _ensure_not_descendant(self, folder_id: str, parent_id: str) -> None:
        current = await self.session.get(Folder, parent_id)
        while current is not None:
            if current.id == folder_id:
                raise AppError(
                    "Folder cannot be moved into its own child",
                    code=ErrorCode.VALIDATION_ERROR,
                    status_code=409,
                )
            if current.parent_id is None:
                return
            current = await self.session.get(Folder, current.parent_id)
