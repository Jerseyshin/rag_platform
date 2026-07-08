import json
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.schemas import GraphEdge, GraphNode

SEGMENT_ID_PATTERN = re.compile(r"^\[segment_id:(?P<segment_id>[^\]]+)\]", re.MULTILINE)


class LightRAGGraphReader:
    """Reads graph details from LightRAG's local JSON storage.

    This is intentionally isolated because these files are LightRAG implementation
    details and may change when the storage backend changes.
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self.working_dir = Path(working_dir or settings.lightrag_working_dir)

    def read_file_graph(self, file_id: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        chunk_to_segment = self._chunk_to_segment_ids(file_id)
        nodes = self._read_nodes(file_id, chunk_to_segment)
        edges = self._read_edges(file_id, chunk_to_segment)
        return nodes, edges

    def read_segments_graph(
        self,
        segment_ids: list[str],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        wanted = {segment_id for segment_id in segment_ids if segment_id}
        if not wanted:
            return [], []

        chunk_to_segment = self._all_chunk_to_segment_ids()
        chunk_ids = {
            chunk_id
            for chunk_id, segment_id in chunk_to_segment.items()
            if segment_id in wanted
        }
        if not chunk_ids:
            return [], []

        nodes = self._read_nodes_for_chunks(chunk_ids, chunk_to_segment)
        edges = self._read_edges_for_chunks(chunk_ids, chunk_to_segment)
        return nodes, edges

    def read_query_graph(
        self,
        query: str,
        segment_ids: list[str],
        *,
        max_seed_nodes: int = 5,
        max_nodes: int = 24,
        max_edges: int = 36,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Builds a query-centered graph from LightRAG's extracted entities.

        Retrieval results tell us which chunks are relevant, but they do not
        necessarily contain an entity whose label is the raw query text. This
        method first tries to locate matching entities globally, then expands
        one hop through relationships. If no entity matches, callers still get
        a useful fallback graph from the retrieved chunks.
        """

        normalized_query = self._normalize_text(query)
        if not normalized_query:
            return self.read_segments_graph(segment_ids)

        chunk_to_segment = self._all_chunk_to_segment_ids()
        wanted_segments = {segment_id for segment_id in segment_ids if segment_id}
        retrieved_chunk_ids = {
            chunk_id
            for chunk_id, segment_id in chunk_to_segment.items()
            if segment_id in wanted_segments
        }

        all_nodes = self._read_nodes_for_chunks(set(chunk_to_segment), chunk_to_segment)
        all_edges = self._read_edges_for_chunks(set(chunk_to_segment), chunk_to_segment)
        node_by_id = {node.id: node for node in all_nodes}
        seed_scores = self._query_seed_scores(
            normalized_query,
            all_nodes,
            retrieved_chunk_ids,
            chunk_to_segment,
        )
        seed_ids = [
            node_id
            for node_id, _score in sorted(
                seed_scores.items(),
                key=lambda item: (-item[1], item[0]),
            )[:max_seed_nodes]
        ]

        if not seed_ids:
            return self.read_segments_graph(segment_ids)

        selected_edges = [
            edge for edge in all_edges if edge.source in seed_ids or edge.target in seed_ids
        ]
        selected_edges.sort(
            key=lambda edge: (
                not self._has_retrieved_source(edge.source_segment_ids, wanted_segments),
                -(len(edge.source_segment_ids or [])),
                edge.source,
                edge.target,
            )
        )
        selected_edges = selected_edges[:max_edges]

        selected_node_ids = set(seed_ids)
        for edge in selected_edges:
            selected_node_ids.add(edge.source)
            selected_node_ids.add(edge.target)

        selected_nodes = [
            node
            for node in all_nodes
            if node.id in selected_node_ids
        ]
        selected_nodes.sort(
            key=lambda node: (
                node.id not in seed_ids,
                seed_ids.index(node.id) if node.id in seed_ids else max_seed_nodes,
                not self._has_retrieved_source(node.source_segment_ids, wanted_segments),
                node.label,
            )
        )
        selected_nodes = selected_nodes[:max_nodes]
        selected_node_ids = {node.id for node in selected_nodes}
        selected_edges = [
            edge
            for edge in selected_edges
            if edge.source in selected_node_ids and edge.target in selected_node_ids
        ]
        return selected_nodes, selected_edges

    def _chunk_to_segment_ids(self, file_id: str) -> dict[str, str]:
        return {
            chunk_id: segment_id
            for chunk_id, segment_id in self._all_chunk_to_segment_ids().items()
            if chunk_id.startswith(f"{file_id}-chunk-")
        }

    def _all_chunk_to_segment_ids(self) -> dict[str, str]:
        chunks = self._read_json("kv_store_text_chunks.json", default={})
        mapping: dict[str, str] = {}
        if not isinstance(chunks, dict):
            return mapping
        for chunk_id, payload in chunks.items():
            content = str((payload or {}).get("content") or "")
            match = SEGMENT_ID_PATTERN.search(content)
            if match:
                mapping[str(chunk_id)] = match.group("segment_id").strip()
        return mapping

    def _read_nodes(
        self,
        file_id: str,
        chunk_to_segment: dict[str, str],
    ) -> list[GraphNode]:
        data = self._read_json("vdb_entities.json", default={})
        rows = data.get("data") if isinstance(data, dict) else []
        nodes: dict[str, GraphNode] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            source_ids = self._source_ids(row.get("source_id"))
            if not self._belongs_to_file(file_id, source_ids):
                continue
            label = self._clean_label(row.get("entity_name"))
            if not label:
                continue
            content = str(row.get("content") or "")
            description = self._strip_leading_label(content, label)
            segment_ids = self._segment_ids(source_ids, chunk_to_segment)
            existing = nodes.get(label)
            if existing is None:
                nodes[label] = GraphNode(
                    id=label,
                    label=label,
                    description=description or None,
                    source_segment_ids=segment_ids,
                )
            else:
                existing.source_segment_ids = sorted(
                    set(existing.source_segment_ids + segment_ids)
                )
        return list(nodes.values())

    def _read_nodes_for_chunks(
        self,
        chunk_ids: set[str],
        chunk_to_segment: dict[str, str],
    ) -> list[GraphNode]:
        data = self._read_json("vdb_entities.json", default={})
        rows = data.get("data") if isinstance(data, dict) else []
        nodes: dict[str, GraphNode] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            source_ids = self._source_ids(row.get("source_id"))
            matched_sources = [source_id for source_id in source_ids if source_id in chunk_ids]
            if not matched_sources:
                continue
            label = self._clean_label(row.get("entity_name"))
            if not label:
                continue
            content = str(row.get("content") or "")
            description = self._strip_leading_label(content, label)
            segment_ids = self._segment_ids(matched_sources, chunk_to_segment)
            existing = nodes.get(label)
            if existing is None:
                nodes[label] = GraphNode(
                    id=label,
                    label=label,
                    description=description or None,
                    source_segment_ids=segment_ids,
                )
            else:
                existing.source_segment_ids = sorted(
                    set(existing.source_segment_ids + segment_ids)
                )
        return list(nodes.values())

    def _read_edges(
        self,
        file_id: str,
        chunk_to_segment: dict[str, str],
    ) -> list[GraphEdge]:
        data = self._read_json("vdb_relationships.json", default={})
        rows = data.get("data") if isinstance(data, dict) else []
        edges: dict[str, GraphEdge] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            source_ids = self._source_ids(row.get("source_id"))
            if not self._belongs_to_file(file_id, source_ids):
                continue
            source = self._clean_label(row.get("src_id"))
            target = self._clean_label(row.get("tgt_id"))
            if not source or not target:
                continue
            relation_type, description = self._parse_relation_content(
                str(row.get("content") or "")
            )
            edge_id = str(row.get("__id__") or f"{source}->{target}:{relation_type or ''}")
            segment_ids = self._segment_ids(source_ids, chunk_to_segment)
            existing = edges.get(edge_id)
            if existing is None:
                edges[edge_id] = GraphEdge(
                    id=edge_id,
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    description=description,
                    source_segment_ids=segment_ids,
                )
            else:
                existing.source_segment_ids = sorted(
                    set(existing.source_segment_ids + segment_ids)
                )
        return list(edges.values())

    def _read_edges_for_chunks(
        self,
        chunk_ids: set[str],
        chunk_to_segment: dict[str, str],
    ) -> list[GraphEdge]:
        data = self._read_json("vdb_relationships.json", default={})
        rows = data.get("data") if isinstance(data, dict) else []
        edges: dict[str, GraphEdge] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            source_ids = self._source_ids(row.get("source_id"))
            matched_sources = [source_id for source_id in source_ids if source_id in chunk_ids]
            if not matched_sources:
                continue
            source = self._clean_label(row.get("src_id"))
            target = self._clean_label(row.get("tgt_id"))
            if not source or not target:
                continue
            relation_type, description = self._parse_relation_content(
                str(row.get("content") or "")
            )
            edge_id = str(row.get("__id__") or f"{source}->{target}:{relation_type or ''}")
            segment_ids = self._segment_ids(matched_sources, chunk_to_segment)
            existing = edges.get(edge_id)
            if existing is None:
                edges[edge_id] = GraphEdge(
                    id=edge_id,
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    description=description,
                    source_segment_ids=segment_ids,
                )
            else:
                existing.source_segment_ids = sorted(
                    set(existing.source_segment_ids + segment_ids)
                )
        return list(edges.values())

    def _query_seed_scores(
        self,
        normalized_query: str,
        nodes: list[GraphNode],
        retrieved_chunk_ids: set[str],
        chunk_to_segment: dict[str, str],
    ) -> dict[str, int]:
        retrieved_segment_ids = {
            chunk_to_segment[chunk_id]
            for chunk_id in retrieved_chunk_ids
            if chunk_id in chunk_to_segment
        }
        scores: dict[str, int] = {}
        for node in nodes:
            normalized_label = self._normalize_text(node.label)
            normalized_description = self._normalize_text(node.description or "")
            score = 0
            if normalized_label == normalized_query:
                score += 100
            elif normalized_query in normalized_label:
                score += 80
            elif normalized_label and normalized_label in normalized_query:
                score += 60
            elif normalized_query in normalized_description:
                score += 30

            if not score:
                continue

            if self._has_retrieved_source(node.source_segment_ids, retrieved_segment_ids):
                score += 25
            score += min(len(node.source_segment_ids or []), 10)
            scores[node.id] = score
        return scores

    def _read_json(self, filename: str, *, default: Any) -> Any:
        path = self.working_dir / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _source_ids(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    @staticmethod
    def _belongs_to_file(file_id: str, source_ids: list[str]) -> bool:
        return any(source_id.startswith(f"{file_id}-chunk-") for source_id in source_ids)

    @staticmethod
    def _segment_ids(
        source_ids: list[str],
        chunk_to_segment: dict[str, str],
    ) -> list[str]:
        return sorted(
            {
                chunk_to_segment[source_id]
                for source_id in source_ids
                if source_id in chunk_to_segment
            }
        )

    @staticmethod
    def _strip_leading_label(content: str, label: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if lines and lines[0] == label:
            lines = lines[1:]
        return "\n".join(lines).strip()

    @staticmethod
    def _clean_label(value: Any) -> str:
        return (
            str(value or "")
            .strip()
            .strip('"')
            .strip("'")
            .strip("`")
            .strip()
        )

    @staticmethod
    def _parse_relation_content(content: str) -> tuple[str | None, str | None]:
        relation_type = None
        description = content.strip() or None
        if "\t" in content:
            relation_type, rest = content.split("\t", 1)
            description = rest.strip() or None
        return (relation_type.strip() or None) if relation_type else None, description

    @staticmethod
    def _normalize_text(value: str) -> str:
        return (
            str(value or "")
            .strip()
            .strip('"')
            .strip("'")
            .strip("`")
            .lower()
        )

    @staticmethod
    def _has_retrieved_source(
        source_segment_ids: list[str],
        retrieved_segment_ids: set[str],
    ) -> bool:
        return bool(set(source_segment_ids or []) & retrieved_segment_ids)
