"""LightRAG metadata spike.

This script verifies the contract required by docs/design.md v3.0:

1. Insert text segments with stable metadata:
   segment_id, file_id, filename.
2. Query and recover segment_id from results.
3. Delete or invalidate records by file_id when the SDK supports it.

The script intentionally keeps all LightRAG calls in small adapter methods so
API differences are easy to isolate during the spike.
"""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import inspect
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parents[2]
WORKING_DIR = Path(os.getenv("LIGHTRAG_SPIKE_WORKING_DIR", WORKSPACE / ".spike_lightrag"))


@dataclass(frozen=True)
class SpikeSegment:
    segment_id: str
    file_id: str
    filename: str
    content: str


SEGMENTS = [
    SpikeSegment(
        segment_id="seg_ai_chip_001",
        file_id="file_ai_chip_report",
        filename="ai-chip-report.md",
        content=(
            "segment_id=seg_ai_chip_001 file_id=file_ai_chip_report\n"
            "AI chip demand grew quickly in 2026. Training workloads were led by "
            "large GPU clusters, while inference chips expanded in edge devices."
        ),
    ),
    SpikeSegment(
        segment_id="seg_database_001",
        file_id="file_database_report",
        filename="database-report.md",
        content=(
            "segment_id=seg_database_001 file_id=file_database_report\n"
            "PostgreSQL with pgvector can store embeddings for retrieval systems. "
            "Operational simplicity is its main advantage for internal platforms."
        ),
    ),
]


class WhitespaceTokenizer:
    def encode(self, content: str) -> list[int]:
        return [ord(char) for char in content]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


def require_lightrag() -> tuple[Any, Any | None]:
    try:
        from lightrag import LightRAG  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "LightRAG is not installed. Install dependencies first, for example:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install lightrag-hku\n"
        ) from exc

    try:
        from lightrag import QueryParam  # type: ignore
    except Exception:
        QueryParam = None

    return LightRAG, QueryParam


def print_line(value: str = "") -> None:
    print(value, flush=True)


def print_signature(name: str, obj: Any) -> None:
    try:
        signature = str(inspect.signature(obj))
    except Exception as exc:
        signature = f"<unavailable: {exc}>"
    print_line(f"{name}: {signature}")


async def mock_embedding(texts: list[str], **_: Any) -> list[list[float]]:
    import numpy as np

    keywords = [
        "ai",
        "chip",
        "demand",
        "training",
        "inference",
        "postgresql",
        "pgvector",
        "database",
    ]
    embeddings: list[list[float]] = []
    for text in texts:
        lowered = text.lower()
        vector = [float(lowered.count(keyword)) for keyword in keywords]
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector.extend(
            [((digest[index % len(digest)] / 255.0) * 0.02) for index in range(24)]
        )
        embeddings.append(vector)
    return np.array(embeddings, dtype=np.float32)


async def mock_llm(prompt: str, **_: Any) -> str:
    if "entity" in prompt.lower() or "relationship" in prompt.lower():
        return json.dumps(
            {
                "entities": [
                    {
                        "entity_name": "AI chip",
                        "entity_type": "technology",
                        "description": "AI accelerator hardware",
                    }
                ],
                "relationships": [],
            },
            ensure_ascii=False,
        )
    return "Mock LLM response for LightRAG spike."


def build_lightrag(LightRAG: Any) -> Any:
    from lightrag.utils import EmbeddingFunc, Tokenizer  # type: ignore

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "working_dir": str(WORKING_DIR),
        "embedding_func": EmbeddingFunc(embedding_dim=32, func=mock_embedding),
        "llm_model_func": mock_llm,
        "tokenizer": Tokenizer(model_name="spike-whitespace", tokenizer=WhitespaceTokenizer()),
        "tiktoken_model_name": "",
        "chunk_token_size": 256,
        "chunk_overlap_token_size": 32,
        "cosine_better_than_threshold": -1.0,
        "cosine_threshold": -1.0,
    }

    try:
        print_line("Calling LightRAG constructor...")
        rag = LightRAG(**kwargs)
        print_line("LightRAG constructor returned.")
        return rag
    except TypeError as exc:
        raise SystemExit(
            "Could not initialize LightRAG with only working_dir. "
            "The SDK likely needs explicit LLM/embedding functions for this version.\n"
            f"Original error: {exc}"
        ) from exc


async def maybe_call_async(func: Any, *args: Any, **kwargs: Any) -> Any:
    result = func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def insert_segment(rag: Any, segment: SpikeSegment) -> None:
    if hasattr(rag, "ainsert"):
        await maybe_call_async(
            rag.ainsert,
            segment.content,
            ids=segment.file_id,
            file_paths=segment.filename,
        )
        return

    if hasattr(rag, "insert"):
        await maybe_call_async(
            rag.insert,
            segment.content,
            ids=segment.file_id,
            file_paths=segment.filename,
        )
        return

    raise RuntimeError("LightRAG instance has no insert/ainsert method")


async def query(rag: Any, QueryParam: Any | None, question: str) -> Any:
    if hasattr(rag, "aquery_data"):
        param = QueryParam(mode="naive", top_k=5) if QueryParam is not None else None
        if param is not None:
            return await maybe_call_async(rag.aquery_data, question, param=param)
        return await maybe_call_async(rag.aquery_data, question)

    if hasattr(rag, "aquery"):
        if QueryParam is not None:
            try:
                return await maybe_call_async(rag.aquery, question, param=QueryParam(mode="global"))
            except TypeError:
                pass
        return await maybe_call_async(rag.aquery, question)

    if hasattr(rag, "query"):
        if QueryParam is not None:
            try:
                return await maybe_call_async(rag.query, question, param=QueryParam(mode="global"))
            except TypeError:
                pass
        return await maybe_call_async(rag.query, question)

    raise RuntimeError("LightRAG instance has no query/aquery method")


async def try_delete_file(rag: Any, file_id: str) -> str:
    candidate_methods = [
        "adelete_by_doc_id",
        "delete_by_doc_id",
        "adelete_by_metadata",
        "delete_by_metadata",
        "adelete",
        "delete",
    ]

    for method_name in candidate_methods:
        method = getattr(rag, method_name, None)
        if method is None:
            continue
        try:
            await maybe_call_async(method, file_id=file_id)
            return f"{method_name}(file_id=...)"
        except TypeError:
            try:
                await maybe_call_async(method, file_id)
                return f"{method_name}(file_id)"
            except Exception:
                continue
        except Exception as exc:
            return f"{method_name} exists but failed: {exc}"

    return "No compatible delete method found; read-path filtering is required."


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def inspect_sdk(LightRAG: Any, QueryParam: Any | None) -> None:
    print_signature("LightRAG.__init__", LightRAG)
    if QueryParam is not None:
        print_signature("QueryParam", QueryParam)

    for name in (
        "ainsert",
        "ainsert_custom_chunks",
        "aquery",
        "aquery_data",
        "adelete_by_doc_id",
    ):
        method = getattr(LightRAG, name, None)
        if method is not None:
            print_signature(f"LightRAG.{name}", method)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--introspect-only", action="store_true")
    args = parser.parse_args()

    if os.getenv("LIGHTRAG_SPIKE_RESET", "1") == "1" and WORKING_DIR.exists():
        shutil.rmtree(WORKING_DIR)

    LightRAG, QueryParam = require_lightrag()
    inspect_sdk(LightRAG, QueryParam)
    if args.introspect_only:
        return

    print_line("Building LightRAG...")
    rag = build_lightrag(LightRAG)
    if hasattr(rag, "initialize_storages"):
        print_line("Initializing LightRAG storages...")
        await maybe_call_async(rag.initialize_storages)
        print_line("LightRAG storages initialized.")
    for name in ("insert", "ainsert", "query", "aquery"):
        method = getattr(rag, name, None)
        if method is not None:
            print_signature(f"rag.{name}", method)

    try:
        for segment in SEGMENTS:
            print_line(f"Inserting {segment.segment_id}...")
            await insert_segment(rag, segment)

        result = await query(rag, QueryParam, "Which segment discusses AI chip demand?")
        result_text = flatten_text(result)
        print_line("Query result:")
        print_line(result_text)

        recovered = [segment.segment_id for segment in SEGMENTS if segment.segment_id in result_text]
        print_line(f"Recovered segment ids from result text: {recovered}")

        delete_result = await try_delete_file(rag, "file_ai_chip_report")
        print_line(f"Delete capability: {delete_result}")
    finally:
        if hasattr(rag, "finalize_storages"):
            print_line("Finalizing LightRAG storages...")
            await maybe_call_async(rag.finalize_storages)
            print_line("LightRAG storages finalized.")


if __name__ == "__main__":
    asyncio.run(main())
