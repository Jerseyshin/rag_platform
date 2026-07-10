import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.schemas import (
    CitationInfo,
    KnowledgeGraphResponse,
    RetrieveChunk,
    RetrieveChunkHighlights,
    RetrieveChunkTrace,
    RetrieveResponse,
    RetrievalTrace,
    RetrievalTraceStep,
)
from app.infrastructure.lightrag_graph import LightRAGGraphReader
from app.infrastructure.lightrag_client import LightRAGClient
from app.infrastructure.rerank_client import RerankClient, get_rerank_client
from app.models.file import FileStatus
from app.models.file_segment import FileSegment, SegmentStatus
from app.models.system_config import SystemConfig


class RetrieveService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        lightrag_client: LightRAGClient | None = None,
        graph_reader: LightRAGGraphReader | None = None,
        rerank_client: RerankClient | None = None,
    ) -> None:
        self.session = session
        self.lightrag_client = lightrag_client or LightRAGClient()
        self.graph_reader = graph_reader or LightRAGGraphReader()
        self.rerank_client = rerank_client or (
            get_rerank_client() if settings.rerank_enabled else None
        )

    async def retrieve(
        self,
        *,
        query: str,
        top_k: int | None = None,
    ) -> RetrieveResponse:
        started = time.perf_counter()
        resolved_top_k = top_k or await self._int_config(
            "rag.default_top_k", settings.default_top_k
        )
        search_mode = await self._str_config(
            "rag.search_mode", settings.default_search_mode
        )

        query_result = await self.lightrag_client.query(
            query,
            top_k=resolved_top_k,
            mode=search_mode,
        )

        visible_candidates = []
        seen = set()
        for candidate in query_result.candidates:
            if candidate.segment_id in seen:
                continue
            seen.add(candidate.segment_id)
            visible_candidates.append(candidate)

        segments = await self._load_visible_segments(
            [candidate.segment_id for candidate in visible_candidates]
        )
        by_id = {segment.id: segment for segment in segments}
        ranked_candidates = await self._rerank_candidates(
            query=query,
            candidates=visible_candidates,
            segments_by_id=by_id,
        )

        nodes, edges = self.graph_reader.build_lightrag_result_graph(
            entities=query_result.entities,
            relationships=query_result.relationships,
        )
        metadata = query_result.metadata or {}
        keywords = self._highlight_keywords(query, metadata)

        chunks: list[RetrieveChunk] = []
        for rerank_rank, (candidate, score) in enumerate(ranked_candidates, start=1):
            segment = by_id.get(candidate.segment_id)
            if segment is None:
                continue
            highlights = self._chunk_highlights(
                segment.id,
                keywords=keywords,
                nodes=nodes,
                edges=edges,
            )
            chunks.append(
                RetrieveChunk(
                    segment_id=segment.id,
                    rank=len(chunks) + 1,
                    score=score,
                    content=segment.content,
                    citation=CitationInfo(
                        file_id=segment.file.id,
                        filename=segment.file.filename,
                        location_type=segment.location_type,
                        location=segment.location_value,
                        download_url=f"/files/{segment.file.id}/download",
                    ),
                    highlights=highlights,
                    trace=RetrieveChunkTrace(
                        lightrag_rank=candidate.rank,
                        rerank_rank=rerank_rank,
                        rank_delta=(
                            candidate.rank - rerank_rank
                            if candidate.rank is not None
                            else None
                        ),
                        lightrag_score=candidate.score,
                        rerank_score=score if self.rerank_client is not None else None,
                        routes=self._chunk_routes(
                            highlights=highlights,
                            candidate=candidate,
                            mode=metadata.get("query_mode") or search_mode,
                        ),
                    ),
                )
            )
            if len(chunks) >= resolved_top_k:
                break

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return RetrieveResponse(
            chunks=chunks,
            graph=KnowledgeGraphResponse(
                nodes=nodes,
                edges=edges,
                keywords=metadata.get("keywords"),
                query_mode=metadata.get("query_mode") or search_mode,
                processing_info=metadata.get("processing_info"),
            ),
            trace=self._build_trace(
                mode=metadata.get("query_mode") or search_mode,
                metadata=metadata,
                nodes=nodes,
                edges=edges,
                chunks=chunks,
            ),
            retrieval_time_ms=elapsed_ms,
        )

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

    async def _rerank_candidates(
        self,
        *,
        query: str,
        candidates: list,
        segments_by_id: dict[str, FileSegment],
    ) -> list[tuple[object, float | None]]:
        visible = [
            candidate
            for candidate in candidates
            if candidate.segment_id in segments_by_id
        ]
        if not visible:
            return []
        if self.rerank_client is None:
            return [(candidate, candidate.score) for candidate in visible]

        scores = await self.rerank_client.score(
            query,
            [segments_by_id[candidate.segment_id].content for candidate in visible],
        )
        ranked = list(zip(visible, scores, strict=False))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [(candidate, score) for candidate, score in ranked]

    async def _str_config(self, key: str, default: str) -> str:
        value = await self._config_value(key)
        return value if value not in {None, ""} else default

    async def _int_config(self, key: str, default: int) -> int:
        value = await self._config_value(key)
        if value in {None, ""}:
            return default
        return int(value)

    async def _config_value(self, key: str) -> str | None:
        result = await self.session.execute(
            select(SystemConfig.value).where(SystemConfig.key == key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _highlight_keywords(query: str, metadata: dict) -> list[str]:
        values: list[str] = [query]
        keyword_data = metadata.get("keywords") if isinstance(metadata, dict) else {}
        if isinstance(keyword_data, dict):
            for key in ("low_level", "high_level"):
                items = keyword_data.get(key) or []
                if isinstance(items, list):
                    values.extend(str(item) for item in items)
        return RetrieveService._unique_non_empty(values)

    @staticmethod
    def _chunk_highlights(
        segment_id: str,
        *,
        keywords: list[str],
        nodes: list,
        edges: list,
    ) -> RetrieveChunkHighlights:
        entity_names = [
            node.label
            for node in nodes
            if segment_id in (node.source_segment_ids or [])
        ]
        relationship_names = [
            edge.relation_type or edge.keywords or f"{edge.source} -> {edge.target}"
            for edge in edges
            if segment_id in (edge.source_segment_ids or [])
        ]
        return RetrieveChunkHighlights(
            keywords=keywords,
            entities=RetrieveService._unique_non_empty(entity_names),
            relationships=RetrieveService._unique_non_empty(relationship_names),
        )

    @staticmethod
    def _chunk_routes(
        *,
        highlights: RetrieveChunkHighlights | None,
        candidate,
        mode: str,
    ) -> list[str]:
        routes = []
        if highlights and highlights.entities:
            routes.append("entity")
        if highlights and highlights.relationships:
            routes.append("relationship")
        if mode == "naive":
            routes.append("vector")
        elif not routes:
            routes.append("vector-or-merged" if mode == "mix" else "lightrag-candidate")
        if candidate.score is not None:
            routes.append("scored-by-lightrag")
        return RetrieveService._unique_non_empty(routes)

    @staticmethod
    def _unique_non_empty(values: list[str]) -> list[str]:
        seen = set()
        output = []
        for value in values:
            text = str(value or "").strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            output.append(text)
        return output

    @staticmethod
    def _build_trace(
        *,
        mode: str,
        metadata: dict,
        nodes: list,
        edges: list,
        chunks: list[RetrieveChunk],
    ) -> RetrievalTrace:
        keywords = metadata.get("keywords") if isinstance(metadata, dict) else {}
        if not isinstance(keywords, dict):
            keywords = {}
        normalized_keywords = {
            "low_level": [
                str(item)
                for item in keywords.get("low_level", [])
                if str(item or "").strip()
            ],
            "high_level": [
                str(item)
                for item in keywords.get("high_level", [])
                if str(item or "").strip()
            ],
        }

        processing_info = metadata.get("processing_info") if isinstance(metadata, dict) else {}
        if not isinstance(processing_info, dict):
            processing_info = {}

        rag_nodes = [
            node
            for node in nodes
            if node.retrieval_source
            in {"lightrag_entity", "lightrag_relation_endpoint"}
        ]
        rag_edges = [
            edge for edge in edges if edge.retrieval_source == "lightrag_relationship"
        ]

        return RetrievalTrace(
            mode=mode,
            mode_description=RetrieveService._mode_description(mode),
            keywords=normalized_keywords,
            processing_info={
                key: int(value)
                for key, value in processing_info.items()
                if isinstance(value, int)
            },
            steps=[
                RetrievalTraceStep(
                    name="query_keywords",
                    title="Query 拆解",
                    description="LightRAG 使用 LLM 将问题拆为 low-level 与 high-level keywords。",
                    items=[
                        {"type": "low_level", "keywords": normalized_keywords["low_level"]},
                        {"type": "high_level", "keywords": normalized_keywords["high_level"]},
                    ],
                ),
                RetrievalTraceStep(
                    name="graph_context",
                    title="图谱上下文",
                    description="LightRAG 最终上下文中保留的实体与关系；多跳扩展仅用于前端图谱浏览。",
                    items=[
                        {
                            "type": "entities",
                            "count": len(rag_nodes),
                            "items": [node.label for node in rag_nodes[:12]],
                        },
                        {
                            "type": "relationships",
                            "count": len(rag_edges),
                            "items": [
                                edge.relation_type
                                or edge.keywords
                                or f"{edge.source} -> {edge.target}"
                                for edge in rag_edges[:12]
                            ],
                        },
                    ],
                ),
                RetrievalTraceStep(
                    name="chunk_sources",
                    title="文段来源",
                    description="根据片段关联的实体、关系和关键词推断每条文段为什么进入结果。",
                    items=[
                        {
                            "rank": chunk.rank,
                            "lightrag_rank": chunk.trace.lightrag_rank if chunk.trace else None,
                            "rerank_rank": chunk.trace.rerank_rank if chunk.trace else chunk.rank,
                            "rank_delta": chunk.trace.rank_delta if chunk.trace else None,
                            "lightrag_score": chunk.trace.lightrag_score if chunk.trace else None,
                            "rerank_score": chunk.trace.rerank_score if chunk.trace else None,
                            "segment_id": chunk.segment_id,
                            "filename": chunk.citation.filename,
                            "sources": (
                                chunk.trace.routes
                                if chunk.trace
                                else RetrieveService._chunk_source_labels(chunk)
                            ),
                            "entities": (
                                chunk.highlights.entities if chunk.highlights else []
                            )[:8],
                            "relationships": (
                                chunk.highlights.relationships
                                if chunk.highlights
                                else []
                            )[:8],
                            "keywords": (
                                chunk.highlights.keywords if chunk.highlights else []
                            )[:8],
                        }
                        for chunk in chunks
                    ],
                ),
            ],
        )

    @staticmethod
    def _mode_description(mode: str) -> str:
        descriptions = {
            "local": "local：low-level keywords → 实体向量检索 → 相关关系与 chunks。",
            "global": "global：high-level keywords → 关系向量检索 → 两端实体与 chunks。",
            "hybrid": "hybrid：合并 local 与 global 的实体/关系检索结果。",
            "mix": "mix：hybrid 图谱检索 + 原始 query 的 chunk 向量检索。",
            "naive": "naive：只做 chunk 向量检索，不使用知识图谱实体/关系。",
            "bypass": "bypass：跳过检索上下文构建。",
        }
        return descriptions.get(mode, f"{mode}：使用 LightRAG 配置的检索模式。")

    @staticmethod
    def _chunk_source_labels(chunk: RetrieveChunk) -> list[str]:
        labels = []
        if chunk.highlights and chunk.highlights.entities:
            labels.append("entity-related")
        if chunk.highlights and chunk.highlights.relationships:
            labels.append("relation-related")
        if chunk.highlights and chunk.highlights.keywords:
            labels.append("keyword-match")
        if not labels:
            labels.append("vector-or-merged")
        return labels
