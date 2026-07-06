import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import AppError, ErrorCode
from app.infrastructure.lightrag_client import LightRAGClient


class FakeDocStatus:
    def __init__(self, status_data):
        self.status_data = status_data

    async def get_by_id(self, file_id: str):
        return self.status_data.get(file_id)


class FakeRag:
    def __init__(self, status_data):
        self.doc_status = FakeDocStatus(status_data)
        self.insert_calls = []

    async def ainsert(self, text: str, **kwargs):
        self.insert_calls.append((text, kwargs))


def make_client(status_data) -> LightRAGClient:
    client = LightRAGClient.__new__(LightRAGClient)
    client._rag = FakeRag(status_data)
    client._initialized = True
    return client


def make_segment():
    return SimpleNamespace(
        id="seg_1",
        file_id="file_1",
        segment_index=1,
        location_type="paragraph",
        location_value="1",
        content="测试内容",
    )


def test_insert_segments_accepts_processed_doc_status() -> None:
    client = make_client({"file_1": {"status": "processed"}})

    asyncio.run(
        client.insert_segments(
            file_id="file_1",
            filename="sample.md",
            segments=[make_segment()],
        )
    )

    assert len(client._rag.insert_calls) == 1


def test_insert_segments_rejects_failed_doc_status() -> None:
    client = make_client(
        {
            "file_1": {
                "status": "failed",
                "chunks_count": 3,
                "error_msg": "C[2/3]: file_1-chunk-001",
            }
        }
    )

    with pytest.raises(AppError) as exc_info:
        asyncio.run(
            client.insert_segments(
                file_id="file_1",
                filename="sample.md",
                segments=[make_segment()],
            )
        )

    assert exc_info.value.code == ErrorCode.LIGHTRAG_DOC_FAILED
    assert "C[2/3]" in exc_info.value.detail
