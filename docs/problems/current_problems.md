# Current Problems

## P1. Remove unreliable retrieve threshold

Status: completed

Decision:

- MVP removes `threshold` from the normal retrieve flow.
- LightRAG ranking is not a pure embedding similarity score. It may use entities, relationships, keywords, and graph expansion.
- Current `aquery_data()` chunk results do not provide a stable, explainable score that can safely back a user-facing threshold.
- The previous fallback score of `1.0` is misleading and must be removed.

Implementation tasks:

- [x] P1.1 Remove `threshold` from `RetrieveRequest`.
- [x] P1.2 Stop reading `rag.default_threshold` in `RetrieveService`.
- [x] P1.3 Stop filtering candidates by threshold.
- [x] P1.4 Change retrieve result scoring semantics so the API does not expose fake `1.0` scores.
- [x] P1.5 Remove threshold controls from the frontend retrieve form.
- [x] P1.6 Remove or de-emphasize `rag.default_threshold` from admin-visible runtime config.
- [x] P1.7 Update `docs/design.md` to state that MVP retrieval is controlled by `top_k` and LightRAG ranking, not threshold filtering.
- [x] P1.8 Update tests and run backend/frontend verification.

Acceptance criteria:

- `POST /retrieve` accepts `query` and optional `top_k`, but not `threshold`.
- No response field or UI label implies a reliable similarity score when LightRAG does not provide one.
- Retrieval remains retrieve-only: no final answer generation and no ordinary-user `search_mode`.

## P2. Index view should expose LightRAG graph details

Status: partial

Decision:

- LightRAG indexing is more than application-level file chunking. It extracts and stores entities and relationships for graph-based retrieval.
- The current frontend gives too much visual weight to upload/file chunks and too little weight to indexing state and LightRAG artifacts.
- The main workspace should be redesigned around indexing as the primary surface. Upload should move to a right-side vertical rail.
- The UI should show entity and relationship details, ideally as a file-level knowledge graph, not only summary counts.

Implementation direction:

- The central area should focus on indexing:
  - file status and progress
  - application segment count
  - LightRAG entity details
  - LightRAG relationship details
  - file-level graph visualization
  - latest indexing message/error
  - manual retry/delete/download actions
- The upload area should become a compact right rail:
  - file picker
  - upload queue
  - minimal upload status
- Backend should expose graph data through a dedicated file graph API.
- The first step must be a Spike to confirm whether LightRAG has a stable SDK/storage API for exporting per-file entities and relationships.

Open design question:

- Should graph details be exported from LightRAG internals, or should the application run its own structured entity/relation extraction after indexing?

Proposed MVP:

- Add application-owned graph tables after the Spike confirms the data source:
  - `file_entities`
  - `file_relationships`
- Add `GET /files/{file_id}/graph`.
- Frontend shows a file-level graph plus entity and relationship lists.
- Counts are still useful as summary fields, but they are not sufficient acceptance criteria.

Implementation tasks:

- [x] P2.1 Spike: confirm whether LightRAG can export per-file entities and relationships through a stable API or storage contract.
- [x] P2.2 Decide between LightRAG graph export and application-owned structured extraction.
- [ ] P2.3 Add application graph tables for file entities and relationships.
- [ ] P2.4 Add graph extraction/persistence after successful indexing.
- [x] P2.5 Add `GET /files/{file_id}/graph`.
- [x] P2.6 Redesign the frontend workspace: graph/indexing center, upload right rail.
- [x] P2.7 Add graph visualization and entity/relationship detail panels.
- [x] P2.8 Update `docs/design.md` and add backend/frontend verification.

Acceptance criteria:

- The default workspace visually prioritizes indexing state and graph artifacts.
- Upload is still easy, but no longer dominates the page.
- Completed files can show file-level entity and relationship details.
- The graph UI does not depend directly on an unstable LightRAG internal file format unless that choice is explicitly documented.

## P3. Physical uploaded files should be removed by scheduled cleanup

Status: partial

Decision:

- `DELETE /files/{file_id}` should remain a soft delete on the request path.
- Soft delete must immediately hide the file from retrieve, list/download, and graph responses.
- Physical cleanup should be handled by a scheduled cleanup task, not by the delete request.
- A physical file deletion failure must not make the file visible again.

Recommended lifecycle:

- `completed/failed/pending` -> `deleting` when the user deletes the file.
- `DELETE /files/{file_id}` only performs the fast visibility change:
  - mark application segments and graph rows as deleted or remove them from visible queries
  - mark the file as `deleting`
  - return quickly
- The scheduler scans `deleting` files:
  - call LightRAG delete for the file/doc
  - delete the original uploaded file from disk
  - delete or hide file graph rows
  - mark the file as `deleted`
- If cleanup fails, keep the file hidden, record the error, and let the next scheduled run retry.

Implementation tasks:

- [x] P3.1 Confirm current delete path and where original file paths are stored.
- [x] P3.2 Add a scheduled cleanup step that scans `deleting` files.
- [x] P3.3 Make download return 404/410 as soon as a file enters `deleting`, even before physical deletion.
- [x] P3.4 In scheduled cleanup, delete LightRAG data, graph data, and the physical uploaded file.
- [x] P3.5 Record cleanup failures in `files.error_code/error_msg` or scheduler logs and retry on later runs.
- [ ] P3.6 Add tests for delete visibility, LightRAG cleanup, scheduled physical file removal, and cleanup retry.
- [x] P3.7 Update `docs/design.md` with the scheduled delete lifecycle.

Acceptance criteria:

- Deleted files are immediately invisible to retrieve, download, list, and graph APIs.
- The original uploaded file is eventually removed from disk by the scheduled cleanup task.
- Cleanup failures are visible to admins, retried by later scheduled runs, and do not expose deleted content.

## P4. Admin page layout, config governance, and useful operation logs

Status: completed

Decision:

- The admin page should be an operational console, not a raw dump of scheduler/config data.
- Layout issues must be fixed so panels align cleanly:
  - the "latest task" area in the index task panel should align with pending/processing/failed summaries
  - the failure handling panel should align with the surrounding panels
- Runtime-editable configs must be explicitly whitelisted. Being present in `.env` does not mean a setting should be editable from the UI.
- Configs exposed in admin UI must have clear types, ranges, enums, descriptions, and effective timing.
- Advanced diagnostics should show useful current work and sensitive/key operations, not only coarse success/failure logs.

Config governance proposal:

- Runtime editable:
  - `rag.default_top_k`: integer range, affects future retrieve requests.
  - `rag.search_mode`: enum, affects future retrieve requests.
  - `rag.chunk_size`: integer range, affects only newly indexed files.
  - `rag.chunk_overlap`: integer range and must be smaller than chunk size, affects only newly indexed files.
  - `scheduler.batch_size`: integer range, affects future scheduler runs.
  - `scheduler.max_retries`: integer range, affects future retry decisions.
  - `scheduler.retry_interval_minutes`: integer range, affects future retry scheduling.
  - `scheduler.processing_timeout_minutes`: integer range, affects future timeout recycling.
- Not editable in admin UI:
  - database URL, upload/storage paths, CORS origins, host/port
  - embedding provider, embedding model, embedding base URL/API key, embedding dimension
  - LLM base URL/API key, request timeout, proxy/trust-env flags
  - `rag.llm_model`, because model/runtime gateway changes are deployment-level decisions in MVP
  - `scheduler.interval_minutes`, because runtime interval changes require rescheduling APScheduler jobs and are out of MVP scope
  - LightRAG working directory and low-level concurrency/timeouts unless promoted deliberately
  - any secret or infrastructure endpoint
- Remove from runtime UI:
  - `rag.default_threshold`, because MVP removes threshold.

Observability proposal:

- Add or expose a "current operations" view:
  - current scheduler run state
  - current file id/name
  - stage: parsing/chunking/lightrag/cleanup/retry/delete
  - progress counters and message
- Improve logs around sensitive/key operations:
  - manual scheduler trigger
  - config update with changed keys, but never secret values
  - file delete requested
  - scheduled physical cleanup started/succeeded/failed
  - retry requested
  - graph extraction started/succeeded/failed

Implementation tasks:

- [x] P4.1 Redesign admin panel grid and alignment.
- [x] P4.2 Define admin-exposed config allowlist, types, ranges, enums, and effective timing.
- [x] P4.3 Add backend validation for config updates instead of accepting arbitrary key/value pairs.
- [x] P4.4 Remove `rag.default_threshold` from admin runtime config.
- [x] P4.5 Remove `rag.llm_model` and `scheduler.interval_minutes` from admin-editable runtime config in MVP.
- [x] P4.6 Add current operations API or extend scheduler status with active task details.
- [x] P4.7 Improve scheduler/audit logs for key operations without leaking secrets.
- [x] P4.8 Update `docs/design.md` and frontend admin UI.

Acceptance criteria:

- Admin panels are visually aligned and organized by operational purpose.
- Admin UI only exposes safe runtime configs with validation and clear effective timing.
- Sensitive `.env` values are never returned by admin APIs or displayed in the frontend.
- Advanced diagnostics help answer "what is running now" and "what important operation happened recently".

## P5. UI state requires manual refresh during indexing and cleanup

Status: completed

Decision:

- Users should not need to click refresh to see indexing progress, cleanup state, or task completion.
- The frontend should automatically refresh while there are active files or active scheduler operations.
- Polling should be scoped and adaptive: fast while work is active, slow or stopped when the system is idle.

Current symptoms:

- During file indexing, progress may not update until the refresh button is clicked.
- Admin-triggered indexing and workspace file progress can get out of sync.
- Scheduler/task state and file state are refreshed through separate paths, so one view can look stale while another has changed.

Implementation direction:

- Define a single active-work detector:
  - files in `pending`, `processing`, `deleting`
  - scheduler currently running
  - manual trigger just accepted
  - cleanup/retry operation in progress
- Use one shared polling loop for workspace and admin state while active work exists.
- Poll both file state and admin/scheduler state when either tab needs active task awareness.
- Stop or slow polling after all files are terminal and scheduler is idle.
- Ensure trigger/delete/upload/retry starts polling immediately.
- Optional later enhancement: replace polling with SSE/WebSocket.

Implementation tasks:

- [x] P5.1 Audit current frontend polling conditions and why progress can remain stale.
- [x] P5.2 Centralize polling state instead of splitting workspace/admin refresh decisions.
- [x] P5.3 Start polling immediately after upload, manual scheduler trigger, delete, retry, and cleanup actions.
- [x] P5.4 Keep polling while files are `pending/processing/deleting` or scheduler reports active work.
- [x] P5.5 Add visible "last updated" or subtle loading state so users know the page is live.
- [x] P5.6 Update tests or manual verification steps.

Acceptance criteria:

- Indexing progress updates automatically without clicking refresh.
- File completion/failure/deleting/deleted state appears automatically.
- Admin task state and workspace file state stay consistent during manual and scheduled runs.

## P6. Knowledge graph should follow the retrieve context

Status: completed

Decision:

- Retrieve result rank follows LightRAG's returned order. It is not an embedding-similarity-only ranking.
- The main workspace graph should be query-centered, not file-centered.
- After a retrieve request, the graph panel should show entities and relationships connected to the returned chunks.
- The graph may include entities and relationships from multiple files when the query recalls cross-file context.
- File-level graph remains useful as a file detail action, but it should not be the main workspace graph behavior.

Implementation tasks:

- [x] P6.1 Document retrieve rank semantics as "LightRAG returned order".
- [x] P6.2 Extend graph reader to build graph from retrieved `segment_id`s / LightRAG chunk ids.
- [x] P6.3 Extend `/retrieve` response with `graph`.
- [x] P6.4 Update frontend so running retrieve automatically updates the graph panel.
- [x] P6.5 Keep right-rail file graph button as a detail view.
- [x] P6.6 Show source segment/file hints when available.
- [x] P6.7 Update `docs/design.md` and run verification.

Acceptance criteria:

- A retrieve request returns chunks and a graph for the same retrieved context.
- The graph can include cross-file entities/relationships if the retrieved chunks span multiple files.
- Users do not need to manually select a file to see a graph after retrieval.
