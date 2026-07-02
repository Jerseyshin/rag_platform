from datetime import datetime

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    size: int
    index_status: str
    message: str


class FileInfo(BaseModel):
    file_id: str
    filename: str
    size: int
    content_type: str | None
    file_ext: str | None
    index_status: str
    error_code: str | None
    error_msg: str | None
    retry_count: int
    segment_count: int | None = None
    indexed_at: datetime | None
    created_at: datetime


class FileListResponse(BaseModel):
    items: list[FileInfo]
    total: int
    limit: int
    offset: int


class FileDeleteResponse(BaseModel):
    success: bool
    file_id: str
    index_status: str
    message: str

class SegmentInfo(BaseModel):
    segment_id: str
    file_id: str
    segment_index: int
    content: str
    token_count: int
    location_type: str
    location_value: str
    location_start: int | None
    location_end: int | None
    status: str

