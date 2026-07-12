from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import FileUploadResponse
from app.db.session import get_session
from app.services.file_service import FileService

router = APIRouter(tags=["files"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile,
    folder_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> FileUploadResponse:
    file_record = await FileService(session).upload(file, folder_id=folder_id)
    return FileUploadResponse(
        file_id=file_record.id,
        folder_id=file_record.folder_id,
        filename=file_record.filename,
        size=file_record.file_size_bytes,
        index_status=file_record.index_status,
        message="文件上传成功，将由后台任务完成索引",
    )
