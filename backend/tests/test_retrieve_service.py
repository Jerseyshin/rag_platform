import asyncio
from types import SimpleNamespace

from app.core.schemas import RetrieveChunkHighlights
from app.services.retrieve_service import RetrieveService


class FakeReranker:
    model_name = "fake-reranker"

    async def score(self, query, documents):
        assert query == "query"
        return [0.2 if "first" in document else 0.9 for document in documents]


def test_rerank_candidates_reorders_visible_segments() -> None:
    service = RetrieveService.__new__(RetrieveService)
    service.rerank_client = FakeReranker()
    candidates = [
        SimpleNamespace(segment_id="seg_1", score=None),
        SimpleNamespace(segment_id="seg_2", score=None),
        SimpleNamespace(segment_id="missing", score=None),
    ]
    segments = {
        "seg_1": SimpleNamespace(content="first document"),
        "seg_2": SimpleNamespace(content="second document"),
    }

    ranked = asyncio.run(
        service._rerank_candidates(
            query="query",
            candidates=candidates,
            segments_by_id=segments,
        )
    )

    assert [candidate.segment_id for candidate, _score in ranked] == ["seg_2", "seg_1"]
    assert [score for _candidate, score in ranked] == [0.9, 0.2]


def test_rerank_candidates_keeps_lightrag_order_without_reranker() -> None:
    service = RetrieveService.__new__(RetrieveService)
    service.rerank_client = None
    candidates = [
        SimpleNamespace(segment_id="seg_1", score=0.4),
        SimpleNamespace(segment_id="seg_2", score=0.7),
    ]
    segments = {
        "seg_1": SimpleNamespace(content="first document"),
        "seg_2": SimpleNamespace(content="second document"),
    }

    ranked = asyncio.run(
        service._rerank_candidates(
            query="query",
            candidates=candidates,
            segments_by_id=segments,
        )
    )

    assert [candidate.segment_id for candidate, _score in ranked] == ["seg_1", "seg_2"]
    assert [score for _candidate, score in ranked] == [0.4, 0.7]


def test_chunk_routes_infer_entity_and_relationship_sources() -> None:
    routes = RetrieveService._chunk_routes(
        highlights=RetrieveChunkHighlights(
            entities=["Entity A"],
            relationships=["A -> B"],
        ),
        candidate=SimpleNamespace(score=None),
        mode="mix",
    )

    assert routes == ["entity", "relationship"]


def test_chunk_routes_marks_unlinked_mix_chunk_as_vector_or_merged() -> None:
    routes = RetrieveService._chunk_routes(
        highlights=RetrieveChunkHighlights(),
        candidate=SimpleNamespace(score=None),
        mode="mix",
    )

    assert routes == ["vector-or-merged"]
