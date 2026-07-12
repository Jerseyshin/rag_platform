from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import (
    FolderCreateRequest,
    FolderInfo,
    FolderListResponse,
    FolderUpdateRequest,
)
from app.db.session import get_session
from app.models.folder import Folder
from app.services.folder_service import FolderService

router = APIRouter(prefix="/folders", tags=["folders"])


def to_folder_info(folder: Folder, file_count: int = 0) -> FolderInfo:
    return FolderInfo(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        sort_order=folder.sort_order,
        file_count=file_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.get("", response_model=FolderListResponse)
async def list_folders(
    session: AsyncSession = Depends(get_session),
) -> FolderListResponse:
    folders, counts = await FolderService(session).list()
    return FolderListResponse(
        items=[to_folder_info(folder, counts.get(folder.id, 0)) for folder in folders]
    )


@router.post("", response_model=FolderInfo)
async def create_folder(
    payload: FolderCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> FolderInfo:
    folder = await FolderService(session).create(
        name=payload.name,
        parent_id=payload.parent_id,
    )
    return to_folder_info(folder)


@router.patch("/{folder_id}", response_model=FolderInfo)
async def update_folder(
    folder_id: str,
    payload: FolderUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> FolderInfo:
    folder = await FolderService(session).update(
        folder_id,
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return to_folder_info(folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    await FolderService(session).delete(folder_id)
