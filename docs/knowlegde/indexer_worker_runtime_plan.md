# Indexer Worker Runtime Plan

## Problem

When LightRAG indexing runs inside the FastAPI process, the API event loop can be occupied by parsing, embedding, LLM extraction, graph writes, and LightRAG finalization. During that window the browser may look like it has lost the database connection because normal API requests cannot respond promptly.

## Target Runtime

Run the platform as three local processes:

1. Frontend dev server: serves the Vue UI.
2. FastAPI API server: handles upload, file management, retrieve/query, admin status, and configuration.
3. Python indexer worker: scans pending files, performs LightRAG indexing, updates progress, retries failures, and cleans deleted files.

No Docker is required for this split. PostgreSQL remains the shared coordination point between API and worker.

## Design

- FastAPI no longer starts the heavy indexing scheduler by default.
- A new local worker entrypoint runs the scheduler loop in its own Python process.
- Manual "run once" in the admin UI writes a database signal instead of creating an API background task.
- The worker consumes the manual signal and records the real scheduler log.
- File indexing progress is persisted on the `files` table, so progress survives API restarts and is visible across processes.
- PostgreSQL advisory lock remains in place, so a manual trigger and scheduled worker tick cannot index concurrently.
- The old in-API scheduler remains available behind `RUN_INDEXER_IN_API=true` for emergency rollback or very small demos.

## Database Additions

The `files` table stores durable progress fields:

- `progress_percent`
- `progress_stage`
- `progress_message`
- `progress_processed_chunks`
- `progress_total_chunks`
- `progress_updated_at`

Manual worker coordination uses `system_configs` keys:

- `scheduler.manual_trigger_requested_at`
- `scheduler.manual_trigger_consumed_at`

## Startup Commands

Backend API:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Indexer worker:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.worker.indexer
```

Or from the project root:

```powershell
.\scripts\start_indexer_worker.ps1
```

The worker writes the same runtime logs to console and to:

```text
backend/logs/indexer_worker.log
```

Useful live log command:

```powershell
Get-Content backend\logs\indexer_worker.log -Wait -Tail 80
```

Frontend:

```powershell
cd frontend
npm run dev -- --host 0.0.0.0
```

Before first use after this change, run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

## Runtime Observability

- File progress is still shown through `GET /files` and `GET /files/{file_id}`.
- During LightRAG indexing, chunk progress is parsed from LightRAG logs and persisted back to `files.progress_*`.
- LLM 408/429/5xx responses and connect/read timeouts are logged with model, attempt number, retry flag, status code, and file id when available.
- LLM retry status is also written into `files.progress_message`, so the UI can show whether indexing is waiting on or failing due to the LLM gateway.
- After LLM retries are exhausted for one chunk, later LightRAG LLM calls in the same file index are aborted quickly. This avoids continuing a long index run that will fail at final doc-status validation anyway.
- Delete requests mark the file as `deleting` immediately and write a manual worker signal. If the worker is idle, cleanup starts on the next worker poll instead of waiting for the full scheduler interval.
- If the worker is already indexing a large file, deletion cleanup waits for the current scheduler run/advisory lock to finish to avoid concurrent writes to the same LightRAG storage.

## Rollout Tasks

- [x] Document the worker split plan.
- [x] Add durable file progress columns.
- [x] Persist progress updates to PostgreSQL.
- [x] Add the local indexer worker entrypoint.
- [x] Convert admin manual trigger to a database signal.
- [x] Update runtime docs and `.env.example`.
- [x] Run backend tests and frontend build.
