import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import QueryResponse, RetrieveChunk
from app.infrastructure.llm_client import LLMClient, get_llm_client
from app.services.retrieve_service import RetrieveService


SYSTEM_PROMPT = """你是一个基于企业文件知识库回答问题的 RAG 助手。
你只能依据提供的检索片段回答，不要编造未在片段中出现的事实。
如果片段不足以回答，请明确说明“根据当前知识库片段无法确定”。
回答应使用中文，结构清晰，必要时分点说明。
引用证据时使用 [1]、[2] 这样的编号，对应上下文片段编号。"""


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        retrieve_service: RetrieveService | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.retrieve_service = retrieve_service or RetrieveService(session)
        self.llm_client = llm_client or get_llm_client()

    async def query(
        self,
        *,
        query: str,
        top_k: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> QueryResponse:
        retrieve_response = await self.retrieve_service.retrieve(
            query=query,
            top_k=top_k,
        )

        if not retrieve_response.chunks:
            return QueryResponse(
                answer="根据当前知识库片段无法确定。未检索到可用的相关片段。",
                chunks=[],
                graph=retrieve_response.graph,
                trace=retrieve_response.trace,
                retrieval_time_ms=retrieve_response.retrieval_time_ms,
                generation_time_ms=0,
            )

        started = time.perf_counter()
        answer = await self.llm_client.complete(
            self._build_prompt(query=query, chunks=retrieve_response.chunks),
            system_prompt=SYSTEM_PROMPT,
            temperature=0 if temperature is None else temperature,
            max_tokens=max_tokens,
        )
        generation_time_ms = int((time.perf_counter() - started) * 1000)

        return QueryResponse(
            answer=answer,
            chunks=retrieve_response.chunks,
            graph=retrieve_response.graph,
            trace=retrieve_response.trace,
            retrieval_time_ms=retrieve_response.retrieval_time_ms,
            generation_time_ms=generation_time_ms,
        )

    @staticmethod
    def _build_prompt(*, query: str, chunks: list[RetrieveChunk]) -> str:
        context = "\n\n".join(
            QueryService._format_chunk(index=index, chunk=chunk)
            for index, chunk in enumerate(chunks, start=1)
        )
        return f"""问题：
{query}

检索片段：
{context}

请基于以上片段回答问题。要求：
1. 不要使用片段之外的事实。
2. 关键结论后标注引用编号，例如 [1]。
3. 如果多个片段互相补充，可以合并回答并列出多个引用。
4. 如果证据不足，请直接说明无法确定，并简要说明缺少什么信息。"""

    @staticmethod
    def _format_chunk(*, index: int, chunk: RetrieveChunk) -> str:
        citation = chunk.citation
        score = f"{chunk.score:.4f}" if isinstance(chunk.score, float) else "-"
        return (
            f"[{index}] 文件：{citation.filename}\n"
            f"位置：{citation.location_type} {citation.location}\n"
            f"segment_id：{chunk.segment_id}\n"
            f"score：{score}\n"
            f"内容：{chunk.content}"
        )
