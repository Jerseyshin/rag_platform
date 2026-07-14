import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.infrastructure.embedding_client import EmbeddingClient, get_embedding_client
from app.infrastructure.index_progress import (
    handle_lightrag_log_message,
    start_lightrag_progress,
)
from app.infrastructure.llm_client import LLMClient, get_llm_client
from app.infrastructure.tokenizers import TextTokenizer, get_tokenizer
from app.models.file_segment import FileSegment

SEGMENT_DELIMITER = "\n<|RAG_SEGMENT_END|>\n"
SEGMENT_ID_PATTERN = re.compile(r"^\[segment_id:(?P<segment_id>[^\]]+)\]", re.MULTILINE)
LIGHTRAG_SUCCESS_STATUSES = {"processed", "completed", "success"}
_PROGRESS_HANDLER_INSTALLED = False
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LightRAGCandidate:
    segment_id: str
    rank: int
    score: float | None
    has_explicit_score: bool
    chunk_id: str | None
    file_path: str | None
    raw_content: str


@dataclass(frozen=True)
class LightRAGQueryResult:
    candidates: list[LightRAGCandidate]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    metadata: dict[str, Any]


class LightRAGClient:
    def __init__(
        self,
        *,
        embedding_client: EmbeddingClient | None = None,
        llm_client: LLMClient | None = None,
        tokenizer: TextTokenizer | None = None,
    ) -> None:
        self.embedding_client = embedding_client or get_embedding_client()
        self.llm_client = llm_client or get_llm_client()
        self.tokenizer = tokenizer or get_tokenizer(strict=True)
        self._rag: Any | None = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._ensure_progress_log_handler()

        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc, Tokenizer

        embedding_client = self.embedding_client
        llm_client = self.llm_client

        async def embedding_func(texts: list[str]) -> np.ndarray:
            return await embedding_client.embed(texts)

        async def llm_model_func(prompt: str, **kwargs: Any) -> str:
            return await llm_client.complete(prompt, **kwargs)

        working_dir = settings.resolve_path(settings.lightrag_working_dir)
        self._rag = LightRAG(
            working_dir=working_dir,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_client.embedding_dim,
                func=embedding_func,
                model_name=embedding_client.model_name,
            ),
            llm_model_func=llm_model_func,
            tokenizer=Tokenizer(
                model_name=self.tokenizer.model_name,
                tokenizer=self.tokenizer,
            ),
            tiktoken_model_name="",
            chunk_token_size=settings.lightrag_chunk_token_size,
            chunk_overlap_token_size=settings.lightrag_chunk_overlap_token_size,
            llm_model_max_async=settings.lightrag_llm_model_max_async,
            embedding_func_max_async=settings.lightrag_embedding_func_max_async,
            default_embedding_timeout=settings.lightrag_default_embedding_timeout,
            default_llm_timeout=settings.lightrag_default_llm_timeout,
        )
        await self._maybe_await(self._rag.initialize_storages())
        self._initialized = True

    async def finalize(self) -> None:
        if self._rag is not None and hasattr(self._rag, "finalize_storages"):
            await self._maybe_await(self._rag.finalize_storages())
        self._initialized = False
        self._rag = None

    async def insert_segments(
        self,
        *,
        file_id: str,
        filename: str,
        segments: list[FileSegment],
    ) -> None:
        if not segments:
            return
        await self.initialize()
        assert self._rag is not None

        full_text = SEGMENT_DELIMITER.join(
            self._format_segment(segment) for segment in segments
        )
        lightrag_file_path = f"{file_id}_{filename}"
        logger.info(
            "LightRAG insert started file_id=%s filename=%s segments=%s",
            file_id,
            filename,
            len(segments),
        )
        start_lightrag_progress(file_id, total_chunks=len(segments))
        await self._maybe_await(
            self._rag.ainsert(
                full_text,
                split_by_character=SEGMENT_DELIMITER,
                split_by_character_only=True,
                ids=file_id,
                file_paths=lightrag_file_path,
            )
        )
        await self._ensure_doc_processed(file_id)
        logger.info(
            "LightRAG insert completed file_id=%s filename=%s",
            file_id,
            filename,
        )

    async def query(
        self,
        query: str,
        *,
        top_k: int,
        mode: str,
    ) -> LightRAGQueryResult:
        await self.initialize()
        assert self._rag is not None

        from lightrag import QueryParam

        result = await self._maybe_await(
            self._rag.aquery_data(
                query,
                param=QueryParam(
                    mode=mode,
                    top_k=top_k,
                    chunk_top_k=settings.lightrag_query_chunk_top_k,
                    max_entity_tokens=settings.lightrag_query_max_entity_tokens,
                    max_relation_tokens=settings.lightrag_query_max_relation_tokens,
                    max_total_tokens=settings.lightrag_query_max_total_tokens,
                    include_references=True,
                    enable_rerank=False,
                ),
            )
        )
        return LightRAGQueryResult(
            candidates=self._parse_candidates(result),
            entities=self._parse_entities(result),
            relationships=self._parse_relationships(result),
            metadata=((result or {}).get("metadata") or {}),
        )

    async def delete_file(self, file_id: str) -> None:
        await self.initialize()
        assert self._rag is not None
        await self._maybe_await(self._rag.adelete_by_doc_id(file_id))

    def _format_segment(self, segment: FileSegment) -> str:
        location = f"{segment.location_type}:{segment.location_value}"
        return (
            f"[segment_id:{segment.id}]\n"
            f"[file_id:{segment.file_id}]\n"
            f"[segment_index:{segment.segment_index}]\n"
            f"[location:{location}]\n"
            f"{segment.content}"
        )

    def _parse_candidates(self, result: dict[str, Any]) -> list[LightRAGCandidate]:
        chunks = ((result or {}).get("data") or {}).get("chunks") or []
        candidates: list[LightRAGCandidate] = []

        for rank, chunk in enumerate(chunks, start=1):
            content = str(chunk.get("content") or "")
            segment_id = self.recover_segment_id(content)
            if not segment_id:
                continue

            score = self._extract_score(chunk)
            candidates.append(
                LightRAGCandidate(
                    segment_id=segment_id,
                    rank=rank,
                    score=score,
                    has_explicit_score=score is not None,
                    chunk_id=chunk.get("chunk_id"),
                    file_path=chunk.get("file_path"),
                    raw_content=content,
                )
            )

        return candidates

    def _parse_entities(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        entities = ((result or {}).get("data") or {}).get("entities") or []
        return [entity for entity in entities if isinstance(entity, dict)]

    def _parse_relationships(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        relationships = ((result or {}).get("data") or {}).get("relationships") or []
        return [relationship for relationship in relationships if isinstance(relationship, dict)]

    @staticmethod
    def recover_segment_id(content: str) -> str | None:
        match = SEGMENT_ID_PATTERN.search(content or "")
        if not match:
            return None
        return match.group("segment_id").strip()

    @staticmethod
    def strip_segment_header(content: str) -> str:
        lines = []
        for line in (content or "").splitlines():
            if line.startswith("[") and "]" in line:
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _extract_score(self, chunk: dict[str, Any]) -> float | None:
        for key in ("score", "similarity", "distance"):
            value = chunk.get(key)
            if value is None:
                continue
            try:
                score = float(value)
            except (TypeError, ValueError):
                continue
            if key == "distance":
                return max(0.0, 1.0 - score)
            return score
        return None

    async def _ensure_doc_processed(self, file_id: str) -> None:
        status_data = await self._get_doc_status(file_id)
        status = self._status_value(self._status_field(status_data, "status"))
        logger.info("LightRAG doc status file_id=%s status=%s", file_id, status)
        if status in LIGHTRAG_SUCCESS_STATUSES:
            return

        error_msg = self._status_field(status_data, "error_msg")
        chunks_count = self._status_field(status_data, "chunks_count")
        detail_parts = [f"LightRAG document {file_id} status is {status or 'unknown'}"]
        if chunks_count not in {None, ""}:
            detail_parts.append(f"chunks_count={chunks_count}")
        if error_msg:
            detail_parts.append(f"error_msg={error_msg}")

        raise AppError(
            "; ".join(detail_parts),
            code=ErrorCode.LIGHTRAG_DOC_FAILED,
            status_code=502,
        )

    async def _get_doc_status(self, file_id: str) -> Any:
        assert self._rag is not None
        doc_status = getattr(self._rag, "doc_status", None)
        if doc_status is None or not hasattr(doc_status, "get_by_id"):
            raise AppError(
                "LightRAG doc_status storage is unavailable",
                code=ErrorCode.LIGHTRAG_DOC_FAILED,
                status_code=502,
            )
        return await self._maybe_await(doc_status.get_by_id(file_id))

    @staticmethod
    def _status_field(status_data: Any, field_name: str) -> Any:
        if status_data is None:
            return None
        if isinstance(status_data, dict):
            return status_data.get(field_name)
        return getattr(status_data, field_name, None)

    @staticmethod
    def _status_value(value: Any) -> str | None:
        if value is None:
            return None
        raw = getattr(value, "value", value)
        return str(raw).strip().lower()

    async def _maybe_await(self, value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value

    @staticmethod
    def _ensure_progress_log_handler() -> None:
        global _PROGRESS_HANDLER_INSTALLED
        if _PROGRESS_HANDLER_INSTALLED:
            return
        logging.getLogger("lightrag").addHandler(_LightRAGProgressLogHandler())
        _PROGRESS_HANDLER_INSTALLED = True


class _LightRAGProgressLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            handle_lightrag_log_message(record.getMessage())
        except Exception:
            # Logging handlers must never break LightRAG indexing.
            pass
