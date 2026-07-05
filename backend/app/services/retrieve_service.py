import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.schemas import CitationInfo, RetrieveChunk, RetrieveResponse
from app.infrastructure.lightrag_client import LightRAGClient
from app.models.file import FileStatus
from app.models.file_segment import FileSegment, SegmentStatus
from app.models.system_config import SystemConfig


class RetrieveService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        lightrag_client: LightRAGClient | None = None,
    ) -> None:
        self.session = session
        self.lightrag_client = lightrag_client or LightRAGClient()

    async def retrieve(
        self,
        *,
        question: str,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> RetrieveResponse:
        started = time.perf_counter()
        resolved_top_k = top_k or await self._int_config(
            "rag.default_top_k", settings.default_top_k
        )
        resolved_threshold = (
            threshold
            if threshold is not None
            else await self._float_config(
                "rag.default_threshold", settings.default_threshold
            )
        )
        search_mode = await self._str_config(
            "rag.search_mode", settings.default_search_mode
        )

        candidates = await self.lightrag_client.query(
            question,
            top_k=resolved_top_k,
            mode=search_mode,
        )

        visible_candidates = []
        seen = set()
        for candidate in candidates:
            if candidate.segment_id in seen:
                continue
            if candidate.has_explicit_score and (candidate.score or 0.0) < resolved_threshold:
                continue
            seen.add(candidate.segment_id)
            visible_candidates.append(candidate)

        segments = await self._load_visible_segments(
            [candidate.segment_id for candidate in visible_candidates]
        )
        by_id = {segment.id: segment for segment in segments}

        chunks: list[RetrieveChunk] = []
        for candidate in visible_candidates:
            segment = by_id.get(candidate.segment_id)
            if segment is None:
                continue
            chunks.append(
                RetrieveChunk(
                    segment_id=segment.id,
                    rank=len(chunks) + 1,
                    score=candidate.score if candidate.score is not None else 1.0,
                    content=segment.content,
                    citation=CitationInfo(
                        file_id=segment.file.id,
                        filename=segment.file.filename,
                        location_type=segment.location_type,
                        location=segment.location_value,
                        download_url=f"/files/{segment.file.id}/download",
                    ),
                )
            )
            if len(chunks) >= resolved_top_k:
                break

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return RetrieveResponse(chunks=chunks, retrieval_time_ms=elapsed_ms)

    async def _load_visible_segments(self, segment_ids: list[str]) -> list[FileSegment]:
        if not segment_ids:
            return []

        stmt = (
            select(FileSegment)
            .options(selectinload(FileSegment.file))
            .where(FileSegment.id.in_(segment_ids))
            .where(FileSegment.status == SegmentStatus.INDEXED.value)
            .where(FileSegment.file.has(index_status=FileStatus.COMPLETED.value))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _str_config(self, key: str, default: str) -> str:
        value = await self._config_value(key)
        return value if value not in {None, ""} else default

    async def _int_config(self, key: str, default: int) -> int:
        value = await self._config_value(key)
        if value in {None, ""}:
            return default
        return int(value)

    async def _float_config(self, key: str, default: float) -> float:
        value = await self._config_value(key)
        if value in {None, ""}:
            return default
        return float(value)

    async def _config_value(self, key: str) -> str | None:
        result = await self.session.execute(
            select(SystemConfig.value).where(SystemConfig.key == key)
        )
        return result.scalar_one_or_none()
