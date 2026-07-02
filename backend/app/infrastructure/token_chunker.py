from dataclasses import dataclass

from app.infrastructure.document_parser import ParsedBlock


@dataclass(frozen=True)
class TextChunk:
    content: str
    token_count: int
    location_type: str
    location_value: str
    location_start: int | None
    location_end: int | None


class TokenChunker:
    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 200) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, blocks: list[ParsedBlock]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for block in blocks:
            tokens = self._tokenize(block.text)
            if not tokens:
                continue

            start = 0
            while start < len(tokens):
                end = min(start + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start:end]
                chunks.append(
                    TextChunk(
                        content=" ".join(chunk_tokens),
                        token_count=len(chunk_tokens),
                        location_type=block.location_type,
                        location_value=block.location_value,
                        location_start=block.location_start,
                        location_end=block.location_end,
                    )
                )
                if end == len(tokens):
                    break
                start = max(end - self.chunk_overlap, start + 1)
        return chunks

    def _tokenize(self, text: str) -> list[str]:
        return text.split()

