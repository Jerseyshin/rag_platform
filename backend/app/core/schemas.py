from datetime import datetime

from pydantic import BaseModel, Field


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


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class CitationInfo(BaseModel):
    file_id: str
    filename: str
    location_type: str
    location: str
    download_url: str


class RetrieveChunk(BaseModel):
    segment_id: str
    rank: int
    score: float
    content: str
    citation: CitationInfo


class RetrieveResponse(BaseModel):
    chunks: list[RetrieveChunk]
    retrieval_time_ms: int
