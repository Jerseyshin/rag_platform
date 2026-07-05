import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import settings


class TextTokenizer(Protocol):
    model_name: str

    def encode(self, text: str) -> list[Any]:
        ...

    def decode(self, tokens: list[Any]) -> str:
        ...


class MixedTextTokenizer:
    """Dependency-free tokenizer fallback for local development."""

    model_name = "mixed-text-fallback"
    _pattern = re.compile(r"\s*(?:[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s])")

    def encode(self, text: str) -> list[str]:
        return [token for token in self._pattern.findall(text.strip()) if token]

    def decode(self, tokens: list[str]) -> str:
        return "".join(tokens)


class HuggingFaceTokenizer:
    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: str | None = None,
        local_files_only: bool = True,
    ) -> None:
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "transformers is required for Hugging Face tokenizers"
            ) from exc

        self.model_name = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(
            self._resolve_model_ref(model_name, cache_dir),
            cache_dir=cache_dir,
            local_files_only=local_files_only,
            use_fast=True,
        )

    def encode(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def decode(self, tokens: list[int]) -> str:
        return self.tokenizer.decode(
            tokens,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

    def _resolve_model_ref(self, model_name: str, cache_dir: str | None) -> str:
        if not cache_dir:
            return model_name

        local_path = Path(cache_dir) / Path(*model_name.split("/"))
        if local_path.exists():
            return str(local_path)
        return model_name


@lru_cache(maxsize=8)
def get_tokenizer(
    model_name: str | None = None,
    cache_dir: str | None = None,
    local_files_only: bool | None = None,
    strict: bool | None = None,
) -> TextTokenizer:
    model = model_name or settings.default_tokenizer_model
    cache = cache_dir or settings.tokenizer_cache_dir
    local_only = (
        settings.tokenizer_local_files_only
        if local_files_only is None
        else local_files_only
    )
    strict_mode = settings.tokenizer_strict if strict is None else strict

    try:
        return HuggingFaceTokenizer(
            model,
            cache_dir=cache,
            local_files_only=local_only,
        )
    except Exception:
        if strict_mode:
            raise
        return MixedTextTokenizer()
