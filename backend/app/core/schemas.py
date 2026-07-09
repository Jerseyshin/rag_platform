from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    next_retry_at: datetime | None = None
    segment_count: int | None = None
    progress_percent: int | None = None
    progress_stage: str | None = None
    progress_message: str | None = None
    progress_processed_chunks: int | None = None
    progress_total_chunks: int | None = None
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


class GraphNode(BaseModel):
    id: str
    label: str
    entity_type: str | None = None
    description: str | None = None
    source_segment_ids: list[str] = []
    retrieval_source: str | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str | None = None
    description: str | None = None
    source_segment_ids: list[str] = []
    weight: float | None = None
    keywords: str | None = None
    retrieval_source: str | None = None


class FileGraphResponse(BaseModel):
    file_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class KnowledgeGraphResponse(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    keywords: dict[str, list[str]] | None = None
    query_mode: str | None = None
    processing_info: dict[str, int] | None = None


class RetrievalTraceStep(BaseModel):
    name: str
    title: str
    description: str
    items: list[dict] = Field(default_factory=list)


class RetrievalTrace(BaseModel):
    mode: str
    mode_description: str
    keywords: dict[str, list[str]] = Field(default_factory=dict)
    processing_info: dict[str, int] = Field(default_factory=dict)
    steps: list[RetrievalTraceStep] = Field(default_factory=list)


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
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)


class CitationInfo(BaseModel):
    file_id: str
    filename: str
    location_type: str
    location: str
    download_url: str


class RetrieveChunkHighlights(BaseModel):
    keywords: list[str] = []
    entities: list[str] = []
    relationships: list[str] = []


class RetrieveChunk(BaseModel):
    segment_id: str
    rank: int
    score: float | None = None
    content: str
    citation: CitationInfo
    highlights: RetrieveChunkHighlights | None = None


class RetrieveResponse(BaseModel):
    chunks: list[RetrieveChunk]
    graph: KnowledgeGraphResponse | None = None
    trace: RetrievalTrace | None = None
    retrieval_time_ms: int


class AdminStatusResponse(BaseModel):
    files: dict[str, int]
    segments: dict[str, int]
    scheduler: dict[str, object]


class ConfigItem(BaseModel):
    key: str
    value: str
    description: str | None = None
    value_type: str | None = None
    min_value: int | None = None
    max_value: int | None = None
    enum_values: list[str] | None = None
    effective_scope: str | None = None


class ConfigUpdateRequest(BaseModel):
    configs: dict[str, str]


class SchedulerTriggerResponse(BaseModel):
    success: bool
    log_id: str
    status: str
    message: str
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0


class SchedulerLogInfo(BaseModel):
    id: str
    trigger_type: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    skipped_files: int
    error_msg: str | None
    details: dict | None


class SchedulerLogsResponse(BaseModel):
    items: list[SchedulerLogInfo]
    total: int
    limit: int
    offset: int
