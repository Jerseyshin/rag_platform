from functools import cached_property
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "RAG-File-Service"
    app_env: str = "development"
    debug: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "rag_platform"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    max_upload_size_mb: int = 20
    upload_dir: str = "uploads"
    allowed_extensions: set[str] = Field(
        default_factory=lambda: {".pdf", ".docx", ".txt", ".md"}
    )
    default_embedding_model: str = "BAAI/bge-m3"
    default_tokenizer_model: str = "BAAI/bge-m3"
    vector_dimension: int = 1024
    embedding_provider: str = "local"
    embedding_cache_dir: str = "offline_cache/tokenizers"
    embedding_local_files_only: bool = True
    embedding_normalize: bool = True
    internal_embedding_base_url: str | None = None
    internal_embedding_api_key: str | None = None
    internal_embedding_timeout: int = 60
    rerank_enabled: bool = False
    rerank_provider: str = "local"
    default_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_cache_dir: str = "../offline_cache/rerankers"
    rerank_local_files_only: bool = True
    rerank_batch_size: int = 8
    rerank_max_length: int = 1024
    tokenizer_cache_dir: str = "offline_cache/tokenizers"
    tokenizer_local_files_only: bool = True
    tokenizer_strict: bool = False
    lightrag_working_dir: str = "lightrag_storage"
    lightrag_chunk_token_size: int = 4096
    lightrag_chunk_overlap_token_size: int = 0
    lightrag_llm_model_max_async: int = 2
    lightrag_embedding_func_max_async: int = 2
    lightrag_default_embedding_timeout: int = 120
    lightrag_default_llm_timeout: int = 240
    lightrag_query_chunk_top_k: int = 10
    lightrag_query_max_entity_tokens: int = 6000
    lightrag_query_max_relation_tokens: int = 8000
    lightrag_query_max_total_tokens: int = 24000
    lightrag_webui_url: str = "http://127.0.0.1:9621/webui"
    default_top_k: int = 5
    default_search_mode: str = "global"
    default_llm_model: str = "Qwen2.5-72B-Internal"
    internal_llm_base_url: str | None = None
    internal_llm_api_key: str | None = None
    internal_llm_timeout: int = 60
    internal_llm_max_retries: int = 3
    internal_llm_trust_env: bool = False
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 5
    scheduler_batch_size: int = 100
    scheduler_max_retries: int = 3
    scheduler_retry_interval_minutes: int = 30
    scheduler_processing_timeout_minutes: int = 30

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes"}:
                return True
        return value

    @cached_property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
