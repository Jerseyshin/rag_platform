from typing import Any, Protocol

import httpx

from app.core.config import settings


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        ...


class ApiLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history_messages:
            messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": kwargs.get("model") or self.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0),
        }
        for key in ("max_tokens", "top_p", "frequency_penalty", "presence_penalty"):
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]


def get_llm_client() -> LLMClient:
    if not settings.internal_llm_base_url:
        raise RuntimeError("INTERNAL_LLM_BASE_URL is required for LightRAG indexing/query")

    return ApiLLMClient(
        base_url=settings.internal_llm_base_url,
        api_key=settings.internal_llm_api_key,
        model_name=settings.default_llm_model,
        timeout=settings.internal_llm_timeout,
    )
