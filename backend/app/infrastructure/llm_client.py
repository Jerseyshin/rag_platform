import asyncio
from contextvars import ContextVar
import logging
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.infrastructure.index_progress import record_lightrag_event


logger = logging.getLogger(__name__)
current_lightrag_file_id: ContextVar[str | None] = ContextVar(
    "current_lightrag_file_id",
    default=None,
)


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
            "stream": False,
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
            retrying = attempt < self.max_retries
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
                if status_code not in {408, 429} and (
                    status_code < 500 or status_code == 501
                ):
                    self._log_attempt_failure(exc, attempt=attempt, retrying=False)
                    raise
                self._log_attempt_failure(exc, attempt=attempt, retrying=retrying)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
                self._log_attempt_failure(exc, attempt=attempt, retrying=retrying)

            if attempt < self.max_retries:
                await asyncio.sleep(self._retry_delay(attempt, last_error))

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM request failed without an explicit error")

    def _log_attempt_failure(
        self,
        exc: Exception,
        *,
        attempt: int,
        retrying: bool,
    ) -> None:
        file_id = current_lightrag_file_id.get()
        attempt_text = f"{attempt + 1}/{self.max_retries + 1}"
        error_type = type(exc).__name__
        status_code = (
            exc.response.status_code
            if isinstance(exc, httpx.HTTPStatusError)
            else None
        )
        logger.warning(
            "LLM request failed file_id=%s model=%s attempt=%s retrying=%s error_type=%s status_code=%s error=%s",
            file_id or "-",
            self.model_name,
            attempt_text,
            retrying,
            error_type,
            status_code,
            exc,
        )
        if file_id:
            reason = f"HTTP {status_code}" if status_code else error_type
            suffix = "，正在重试" if retrying else "，重试已耗尽"
            record_lightrag_event(file_id, f"LLM 调用失败 {attempt_text}：{reason}{suffix}")

    @staticmethod
    def _retry_delay(attempt: int, exc: Exception | None) -> float:
        if isinstance(exc, httpx.HTTPStatusError):
            retry_after = exc.response.headers.get("retry-after")
            if retry_after:
                try:
                    return max(0.0, min(float(retry_after), 30.0))
                except ValueError:
                    pass
        return min(2**attempt, 8)


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
