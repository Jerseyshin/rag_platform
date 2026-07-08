from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import RetrieveRequest, RetrieveResponse
from app.db.session import get_session
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
