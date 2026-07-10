from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from app.core.config import settings


class RerankClient(Protocol):
    model_name: str

    async def score(self, query: str, documents: Sequence[str]) -> list[float]:
        ...


class LocalBgeRerankClient:
    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: str | None = None,
        local_files_only: bool = True,
        batch_size: int = 8,
        max_length: int = 1024,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "torch and transformers are required for local rerank"
            ) from exc

        self.torch = torch
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        model_ref = self._resolve_model_ref(model_name, cache_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_ref,
            cache_dir=cache_dir,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_ref,
            cache_dir=cache_dir,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.model.eval()

    async def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []

        scores: list[float] = []
        for start in range(0, len(documents), self.batch_size):
            batch_docs = list(documents[start : start + self.batch_size])
            pairs = [[query, document] for document in batch_docs]
            inputs = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with self.torch.no_grad():
                logits = self.model(**inputs).logits.view(-1)
                batch_scores = self.torch.sigmoid(logits).detach().cpu().numpy()
            scores.extend(float(score) for score in np.asarray(batch_scores).tolist())
        return scores

    def _resolve_model_ref(self, model_name: str, cache_dir: str | None) -> str:
        if not cache_dir:
            return model_name

        local_path = Path(cache_dir) / Path(*model_name.split("/"))
        if local_path.exists():
            return str(local_path)
        return model_name


@lru_cache(maxsize=2)
def get_rerank_client(provider: str | None = None) -> RerankClient:
    selected = (provider or settings.rerank_provider).lower()

    if selected == "local":
        return LocalBgeRerankClient(
            settings.default_rerank_model,
            cache_dir=settings.rerank_cache_dir,
            local_files_only=settings.rerank_local_files_only,
            batch_size=settings.rerank_batch_size,
            max_length=settings.rerank_max_length,
        )

    raise ValueError(f"Unsupported rerank provider: {selected}")
