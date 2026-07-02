from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.infrastructure.document_parser import DocumentParser
from app.infrastructure.token_chunker import TokenChunker
from app.models.file import File, FileStatus
from app.models.file_segment import FileSegment, SegmentStatus


class SegmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.parser = DocumentParser()

    async def parse_and_store(
        self,
        file_record: File,
        *,
        chunk_size: int = 1024,
        chunk_overlap: int = 200,
    ) -> list[FileSegment]:
        try:
            blocks = self.parser.parse(file_record.file_path)
            chunks = TokenChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap).split(blocks)
            if not chunks:
                raise AppError(
                    "File contains no chunkable text",
                    code=ErrorCode.EMPTY_CONTENT,
                    status_code=422,
                )
        except AppError as exc:
            file_record.index_status = FileStatus.FAILED.value
            file_record.error_code = exc.code.value
            file_record.error_msg = exc.detail
            await self.session.commit()
            raise

        await self.session.execute(delete(FileSegment).where(FileSegment.file_id == file_record.id))

        segments = [
            FileSegment(
                id=f"seg_{uuid4().hex}",
                file_id=file_record.id,
                segment_index=index,
                content=chunk.content,
                token_count=chunk.token_count,
                location_type=chunk.location_type,
                location_value=chunk.location_value,
                location_start=chunk.location_start,
                location_end=chunk.location_end,
                status=SegmentStatus.PENDING.value,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]

        self.session.add_all(segments)
        await self.session.commit()
        return segments
