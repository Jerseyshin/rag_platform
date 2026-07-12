from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import QueryRequest, QueryResponse, RetrieveRequest, RetrieveResponse
from app.db.session import get_session
from app.services.query_service import QueryService
from app.services.retrieve_service import RetrieveService

router = APIRouter(tags=["retrieve"])


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    request: RetrieveRequest,
    session: AsyncSession = Depends(get_session),
) -> RetrieveResponse:
    service = RetrieveService(session)
    return await service.retrieve(
        query=request.query,
        top_k=request.top_k,
    )


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    service = QueryService(session)
    return await service.query(
        query=request.query,
        top_k=request.top_k,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
