from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.errors import AppError, ErrorCode


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    location_type: str
    location_value: str
    location_start: int | None = None
    location_end: int | None = None


class DocumentParser:
    def parse(self, file_path: str | Path) -> list[ParsedBlock]:
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext in {".txt", ".md"}:
            return self._parse_text(path)
        if ext == ".pdf":
            return self._parse_pdf(path)
        if ext == ".docx":
            return self._parse_docx(path)

        raise AppError(
            f"Unsupported file type: {ext}",
            code=ErrorCode.FILE_TYPE_NOT_ALLOWED,
            status_code=415,
        )

    def _parse_text(self, path: Path) -> list[ParsedBlock]:
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            raise AppError("File contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)

        paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
        if not paragraphs:
            raise AppError("File contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)

        return [
            ParsedBlock(text=text, location_type="paragraph", location_value=str(index))
            for index, text in enumerate(paragraphs, start=1)
        ]

    def _parse_pdf(self, path: Path) -> list[ParsedBlock]:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise AppError(
                    "PDF is encrypted",
                    code=ErrorCode.PARSE_ENCRYPTED_PDF,
                    status_code=422,
                )
            blocks = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    blocks.append(
                        ParsedBlock(
                            text=text,
                            location_type="page",
                            location_value=str(index),
                            location_start=index,
                            location_end=index,
                        )
                    )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                f"Failed to parse PDF: {exc}",
                code=ErrorCode.PARSE_ENCRYPTED_PDF,
                status_code=422,
            ) from exc

        if not blocks:
            raise AppError("PDF contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)
        return blocks

    def _parse_docx(self, path: Path) -> list[ParsedBlock]:
        try:
            from docx import Document

            document = Document(str(path))
            blocks = [
                ParsedBlock(
                    text=paragraph.text.strip(),
                    location_type="paragraph",
                    location_value=str(index),
                )
                for index, paragraph in enumerate(document.paragraphs, start=1)
                if paragraph.text.strip()
            ]
        except Exception as exc:
            raise AppError(
                f"Failed to parse DOCX: {exc}",
                code=ErrorCode.EMPTY_CONTENT,
                status_code=422,
            ) from exc

        if not blocks:
            raise AppError("DOCX contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)
        return blocks

