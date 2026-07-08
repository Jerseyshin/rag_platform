# LightRAG Graph Export Spike

Date: 2026-07-08

## Goal

Confirm whether the current LightRAG integration can expose file-level entity and relationship details for the frontend knowledge graph view.

## Findings

- The installed `LightRAG` class exposes graph-related methods such as `get_knowledge_graph`, `get_entity_info`, `get_relation_info`, and `get_graph_labels`.
- The current local storage directory contains graph artifacts:
  - `graph_chunk_entity_relation.graphml`
  - `kv_store_text_chunks.json`
  - `kv_store_entity_chunks.json`
  - `kv_store_relation_chunks.json`
  - `kv_store_full_entities.json`
  - `kv_store_full_relations.json`
  - `vdb_entities.json`
  - `vdb_relationships.json`
- In the local JSON storage, entity and relationship rows contain `source_id` values like `file_id-chunk-000`.
- `kv_store_text_chunks.json` maps LightRAG chunk ids back to chunk content, where the application `segment_id` header is available.
- Therefore, file-level graph data can be recovered by:
  1. filtering entity/relationship rows whose `source_id` starts with `{file_id}-chunk-`
  2. mapping LightRAG chunk ids back to application `segment_id`
  3. returning nodes and edges through an application API

## Decision

For MVP, implement a small isolated adapter that reads LightRAG local JSON storage and exposes:

- `GET /files/{file_id}/graph`
- `nodes`
- `edges`
- `source_segment_ids`

This is intentionally treated as a LightRAG local-storage adapter, not a stable domain model. If the project later switches LightRAG storage backend or version, replace this adapter with either:

- a stable LightRAG SDK graph export API, or
- application-owned `file_entities` / `file_relationships` tables populated after indexing.

## Risk

This MVP depends on LightRAG local JSON file shape. The dependency is isolated in `backend/app/infrastructure/lightrag_graph.py`.
