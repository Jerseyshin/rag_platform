# LightRAG Metadata Spike

Status: completed with one environment-dependent follow-up

## Goal

Verify the LightRAG integration contract required by `docs/design.md v3.0`:

- Insert content with stable file identity.
- Query retrieve-only structured data and recover application `segment_id`.
- Delete indexed data by file id.
- Confirm PostgreSQL/pgvector support path and required configuration.

## Script

Spike script:

```text
scripts/spikes/lightrag_metadata_spike.py
```

Run from repository root:

```powershell
.\.venv\Scripts\python.exe scripts\spikes\lightrag_metadata_spike.py
```

SDK signature only:

```powershell
.\.venv\Scripts\python.exe scripts\spikes\lightrag_metadata_spike.py --introspect-only
```

## Environment

- Python: 3.14.6
- Package installed: `lightrag-hku==1.5.4`
- Local spike storage: `.spike_lightrag/`
- Local vector storage used for executable spike: `NanoVectorDBStorage`

## Findings

### SDK Interfaces

Confirmed available interfaces:

- `LightRAG.ainsert(input, ids, file_paths, ...)`
- `LightRAG.ainsert_custom_chunks(full_text, text_chunks, doc_id)`
- `LightRAG.aquery_data(query, QueryParam(...))`
- `LightRAG.adelete_by_doc_id(doc_id)`
- `QueryParam(mode='local'|'global'|'hybrid'|'naive'|'mix'|'bypass', top_k=..., include_references=...)`

Important initialization requirements:

- `initialize_storages()` must be called before insert/query/delete.
- `finalize_storages()` should be called on shutdown.
- `EmbeddingFunc` must return a numpy array, not a Python list.
- The default tiktoken model initialization hung in this local environment, so the spike used an explicit reversible tokenizer.

### Insert

Direct arbitrary metadata insertion is not supported by the SDK path tested. The workable path is:

- Use `ids=file_id`.
- Use `file_paths=filename`.
- Embed `segment_id` in the chunk/document content header, or maintain a `chunk_id -> segment_id` mapping in the application.

`ainsert_custom_chunks(..., doc_id=file_id)` can insert custom chunks, but in this spike it did not create document status in the way required by `adelete_by_doc_id`. Therefore the safer MVP path is `ainsert(..., ids=file_id, file_paths=filename)` unless later testing proves a reliable custom chunk deletion path.

### Query

`aquery_data()` is the correct retrieve-only API. In `mode='naive'`, it returned structured data:

- `chunks[].content`
- `chunks[].chunk_id`
- `chunks[].file_path`
- `references[]`

The spike recovered application `segment_id` from the returned content header:

```text
Recovered segment ids from result text: ['seg_ai_chip_001', 'seg_database_001']
```

For production, the application should still treat `file_segments` as the response source of truth and use LightRAG results only to recover candidate segment ids or chunk ids.

### Delete

`adelete_by_doc_id(file_id)` exists and successfully deleted the indexed document for `file_ai_chip_report` in the local storage spike.

Read-path filtering is still required by design so deletion is immediately effective even before LightRAG physical cleanup completes.

### PostgreSQL / pgvector

The installed SDK contains PostgreSQL storage implementations:

- `PGKVStorage`
- `PGVectorStorage`
- `PGGraphStorage`
- `PGDocStatusStorage`

Required environment variables from the SDK:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DATABASE`

The local machine did not have `psql`, PostgreSQL environment variables, or a project `.env`, so a real PostgreSQL connection test was not run in T1. This remains a deployment-environment validation item for the first database-backed backend task.

## LightRAGClient Contract

The backend adapter should expose this stable interface:

```python
class LightRAGClient:
    async def initialize(self) -> None: ...
    async def finalize(self) -> None: ...
    async def insert_file_segments(
        self,
        file_id: str,
        filename: str,
        segments: list[AppSegment],
    ) -> None: ...
    async def query(
        self,
        question: str,
        *,
        top_k: int,
        threshold: float,
        mode: str,
    ) -> list[LightRAGCandidate]: ...
    async def delete_file(self, file_id: str) -> None: ...
```

Adapter rules:

- Call LightRAG with `ids=file_id` and `file_paths=filename`.
- Prefix each segment/chunk content with a machine-readable `segment_id`.
- Use `aquery_data()` for retrieve-only results.
- Disable rerank unless a rerank model is configured.
- Recover `segment_id` from returned content or from a stored `chunk_id -> segment_id` mapping.
- Use `adelete_by_doc_id(file_id)` for physical cleanup.
- Keep application read-path filtering as the authoritative deletion guard.

## Design Updates Applied

`docs/design.md` was updated to remove the incorrect assumption that arbitrary `segment_id/file_id/filename` metadata can be written directly through the tested SDK path.
