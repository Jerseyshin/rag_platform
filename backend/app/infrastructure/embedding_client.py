from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence

import httpx
import numpy as np

from app.core.config import settings


class EmbeddingClient(Protocol):
    model_name: str
    embedding_dim: int

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        ...


class LocalBgeM3EmbeddingClient:
    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: str | None = None,
        local_files_only: bool = True,
        embedding_dim: int = 1024,
        normalize_embeddings: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers and torch are required for local embeddings"
            ) from exc

        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.normalize_embeddings = normalize_embeddings
        self.model = SentenceTransformer(
            self._resolve_model_ref(model_name, cache_dir),
            cache_folder=cache_dir,
            local_files_only=local_files_only,
        )

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        embeddings = self.model.encode(
            list(texts),
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def _resolve_model_ref(self, model_name: str, cache_dir: str | None) -> str:
        if not cache_dir:
            return model_name

        local_path = Path(cache_dir) / Path(*model_name.split("/"))
        if local_path.exists():
            return str(local_path)
        return model_name


class ApiEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        embedding_dim: int,
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json={"model": self.model_name, "input": list(texts)},
            )
            response.raise_for_status()

        payload = response.json()
        vectors = [item["embedding"] for item in payload["data"]]
        return np.asarray(vectors, dtype=np.float32)


@lru_cache(maxsize=4)
def get_embedding_client(provider: str | None = None) -> EmbeddingClient:
    selected = (provider or settings.embedding_provider).lower()

    if selected == "local":
        return LocalBgeM3EmbeddingClient(
            settings.default_embedding_model,
            cache_dir=settings.embedding_cache_dir,
            local_files_only=settings.embedding_local_files_only,
            embedding_dim=settings.vector_dimension,
            normalize_embeddings=settings.embedding_normalize,
        )

    if selected == "api":
        if not settings.internal_embedding_base_url:
            raise RuntimeError("INTERNAL_EMBEDDING_BASE_URL is required")
        return ApiEmbeddingClient(
            base_url=settings.internal_embedding_base_url,
            api_key=settings.internal_embedding_api_key,
            model_name=settings.default_embedding_model,
            embedding_dim=settings.vector_dimension,
            timeout=settings.internal_embedding_timeout,
        )

    raise ValueError(f"Unsupported embedding provider: {selected}")
