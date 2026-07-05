from dataclasses import dataclass

from app.infrastructure.document_parser import ParsedBlock
from app.infrastructure.tokenizers import TextTokenizer, get_tokenizer


@dataclass(frozen=True)
class TextChunk:
    content: str
    token_count: int
    location_type: str
    location_value: str
    location_start: int | None
    location_end: int | None


class TokenChunker:
    def __init__(
        self,
        chunk_size: int = 1024,
        chunk_overlap: int = 200,
        tokenizer: TextTokenizer | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer = tokenizer or get_tokenizer()

    def split(self, blocks: list[ParsedBlock]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for block in blocks:
            tokens = self.tokenizer.encode(block.text)
            if not tokens:
                continue

            start = 0
            while start < len(tokens):
                end = min(start + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start:end]
                chunk_content = self.tokenizer.decode(chunk_tokens).strip()
                if not chunk_content:
                    if end == len(tokens):
                        break
                    start = max(end - self.chunk_overlap, start + 1)
                    continue
                chunks.append(
                    TextChunk(
                        content=chunk_content,
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
