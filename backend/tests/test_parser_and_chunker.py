from pathlib import Path

import pytest

from app.core.errors import AppError, ErrorCode
from app.infrastructure.document_parser import DocumentParser, ParsedBlock
from app.infrastructure.token_chunker import TokenChunker


class CharacterTokenizer:
    def encode(self, text: str) -> list[str]:
        return list(text)

    def decode(self, tokens: list[str]) -> str:
        return "".join(tokens)


def test_text_parser_splits_non_empty_lines(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("第一段\n\n第二段\n", encoding="utf-8")

    blocks = DocumentParser().parse(path)

    assert [block.text for block in blocks] == ["第一段", "第二段"]
    assert [block.location_value for block in blocks] == ["1", "2"]


def test_text_parser_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text(" \n\t\n", encoding="utf-8")

    with pytest.raises(AppError) as exc_info:
        DocumentParser().parse(path)

    assert exc_info.value.code == ErrorCode.EMPTY_CONTENT


def test_parser_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    path.write_text("not supported", encoding="utf-8")

    with pytest.raises(AppError) as exc_info:
        DocumentParser().parse(path)

    assert exc_info.value.code == ErrorCode.FILE_TYPE_NOT_ALLOWED


def test_token_chunker_uses_injected_tokenizer_with_overlap() -> None:
    block = ParsedBlock(
        text="abcdefg",
        location_type="paragraph",
        location_value="1",
    )

    chunks = TokenChunker(
        chunk_size=3,
        chunk_overlap=1,
        tokenizer=CharacterTokenizer(),
    ).split([block])

    assert [chunk.content for chunk in chunks] == ["abc", "cde", "efg"]
    assert [chunk.token_count for chunk in chunks] == [3, 3, 3]
    assert all(chunk.location_type == "paragraph" for chunk in chunks)
