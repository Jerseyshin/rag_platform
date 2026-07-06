from dataclasses import dataclass
from pathlib import Path
import re

from pypdf import PdfReader

from app.core.errors import AppError, ErrorCode

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


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

        if ext == ".txt":
            return self._parse_text(path)
        if ext == ".md":
            return self._parse_markdown(path)
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

    def _parse_markdown(self, path: Path) -> list[ParsedBlock]:
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            raise AppError("File contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)

        blocks: list[ParsedBlock] = []
        current_heading: tuple[int, str] | None = None
        current_lines: list[str] = []
        current_start: int | None = None

        def flush(end_line: int) -> None:
            nonlocal current_heading, current_lines, current_start
            text = "\n".join(line.rstrip() for line in current_lines).strip()
            if not text:
                current_lines = []
                current_start = None
                return

            if current_heading:
                level, title = current_heading
                location_value = f"h{level}:{title}"
            else:
                location_value = "preamble"

            blocks.append(
                ParsedBlock(
                    text=text,
                    location_type="section",
                    location_value=location_value,
                    location_start=current_start,
                    location_end=end_line,
                )
            )
            current_lines = []
            current_start = None

        lines = content.splitlines()
        for line_number, line in enumerate(lines, start=1):
            heading_match = _HEADING_RE.match(line.strip())
            if heading_match:
                flush(line_number - 1)
                current_heading = (
                    len(heading_match.group(1)),
                    heading_match.group(2).strip(),
                )
                current_lines = [line.strip()]
                current_start = line_number
                continue

            if current_start is None and line.strip():
                current_start = line_number
            current_lines.append(line)

        flush(len(lines))

        if not blocks:
            raise AppError("File contains no readable text", code=ErrorCode.EMPTY_CONTENT, status_code=422)
        return blocks

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
