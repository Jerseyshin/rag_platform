import asyncio
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
        max_retries: int = 3,
        trust_env: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.trust_env = trust_env

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

        response = await self._post_with_retries(headers=headers, payload=payload)

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _post_with_retries(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    trust_env=self.trust_env,
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code < 500 or status_code == 501:
                    raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc

            if attempt < self.max_retries:
                await asyncio.sleep(min(2**attempt, 8))

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM request failed without an explicit error")


def get_llm_client() -> LLMClient:
    if not settings.internal_llm_base_url:
        raise RuntimeError("INTERNAL_LLM_BASE_URL is required for LightRAG indexing/query")

    return ApiLLMClient(
        base_url=settings.internal_llm_base_url,
        api_key=settings.internal_llm_api_key,
        model_name=settings.default_llm_model,
        timeout=settings.internal_llm_timeout,
        max_retries=settings.internal_llm_max_retries,
        trust_env=settings.internal_llm_trust_env,
    )
