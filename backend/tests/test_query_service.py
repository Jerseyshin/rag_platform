import asyncio

from app.core.schemas import CitationInfo, RetrieveChunk, RetrieveResponse
from app.services.query_service import QueryService


class FakeRetrieveService:
    def __init__(self, chunks):
        self.chunks = chunks

    async def retrieve(self, *, query, top_k=None):
        assert query == "什么是项目风险？"
        assert top_k == 2
        return RetrieveResponse(
            chunks=self.chunks,
            graph=None,
            trace=None,
            retrieval_time_ms=12,
        )


class FakeLLMClient:
    def __init__(self):
        self.prompt = None
        self.system_prompt = None
        self.kwargs = None
        self.called = False

    async def complete(self, prompt, *, system_prompt=None, **kwargs):
        self.called = True
        self.prompt = prompt
        self.system_prompt = system_prompt
        self.kwargs = kwargs
        return "项目风险是影响项目目标的不确定因素。[1]"


def make_chunk() -> RetrieveChunk:
    return RetrieveChunk(
        segment_id="seg_1",
        rank=1,
        score=0.91,
        content="项目风险是可能影响范围、进度、成本或质量的不确定事件。",
        citation=CitationInfo(
            file_id="f_1",
            filename="risk.md",
            location_type="paragraph",
            location="1",
            download_url="/files/f_1/download",
        ),
    )


def test_query_generates_answer_from_retrieved_chunks() -> None:
    chunk = make_chunk()
    llm = FakeLLMClient()
    service = QueryService(
        None,
        retrieve_service=FakeRetrieveService([chunk]),
        llm_client=llm,
    )

    response = asyncio.run(
        service.query(
            query="什么是项目风险？",
            top_k=2,
            temperature=0.2,
            max_tokens=300,
        )
    )

    assert response.answer == "项目风险是影响项目目标的不确定因素。[1]"
    assert response.chunks == [chunk]
    assert response.retrieval_time_ms == 12
    assert response.generation_time_ms >= 0
    assert llm.called is True
    assert "[1] 文件：risk.md" in llm.prompt
    assert "项目风险是可能影响范围" in llm.prompt
    assert "只能依据提供的检索片段回答" in llm.system_prompt
    assert llm.kwargs["temperature"] == 0.2
    assert llm.kwargs["max_tokens"] == 300


def test_query_returns_no_evidence_answer_without_calling_llm() -> None:
    llm = FakeLLMClient()
    service = QueryService(
        None,
        retrieve_service=FakeRetrieveService([]),
        llm_client=llm,
    )

    response = asyncio.run(
        service.query(query="什么是项目风险？", top_k=2)
    )

    assert "无法确定" in response.answer
    assert response.chunks == []
    assert response.generation_time_ms == 0
    assert llm.called is False
