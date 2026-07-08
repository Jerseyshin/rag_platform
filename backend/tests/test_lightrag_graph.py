import json

from app.infrastructure.lightrag_graph import LightRAGGraphReader


def write_json(path, name, data):
    (path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_query_graph_matches_entity_and_expands_one_hop(tmp_path) -> None:
    write_json(
        tmp_path,
        "kv_store_text_chunks.json",
        {
            "file_1-chunk-0": {"content": "[segment_id:seg_1]\n工程师负责系统设计。"},
            "file_1-chunk-1": {"content": "[segment_id:seg_2]\n团队使用 FastAPI。"},
        },
    )
    write_json(
        tmp_path,
        "vdb_entities.json",
        {
            "data": [
                {
                    "entity_name": '"工程师"',
                    "content": "工程师\n负责设计和实现系统。",
                    "source_id": "file_1-chunk-0",
                },
                {
                    "entity_name": "FastAPI",
                    "content": "FastAPI\n后端框架。",
                    "source_id": "file_1-chunk-1",
                },
            ]
        },
    )
    write_json(
        tmp_path,
        "vdb_relationships.json",
        {
            "data": [
                {
                    "__id__": "rel_1",
                    "src_id": '"工程师"',
                    "tgt_id": "FastAPI",
                    "content": "使用\t工程师使用 FastAPI 构建服务。",
                    "source_id": "file_1-chunk-0,file_1-chunk-1",
                }
            ]
        },
    )

    nodes, edges = LightRAGGraphReader(str(tmp_path)).read_query_graph("工程师", ["seg_1"])

    assert [node.id for node in nodes] == ["工程师", "FastAPI"]
    assert len(edges) == 1
    assert edges[0].source == "工程师"
    assert edges[0].target == "FastAPI"


def test_query_graph_falls_back_to_retrieved_segments_when_no_entity_match(tmp_path) -> None:
    write_json(
        tmp_path,
        "kv_store_text_chunks.json",
        {"file_1-chunk-0": {"content": "[segment_id:seg_1]\n测试内容。"}},
    )
    write_json(
        tmp_path,
        "vdb_entities.json",
        {
            "data": [
                {
                    "entity_name": "测试内容",
                    "content": "测试内容\n用于回退验证。",
                    "source_id": "file_1-chunk-0",
                }
            ]
        },
    )
    write_json(tmp_path, "vdb_relationships.json", {"data": []})

    nodes, edges = LightRAGGraphReader(str(tmp_path)).read_query_graph("不存在", ["seg_1"])

    assert [node.id for node in nodes] == ["测试内容"]
    assert edges == []


def test_build_lightrag_result_graph_uses_actual_retrieval_entities_and_relationships(
    tmp_path,
) -> None:
    write_json(
        tmp_path,
        "kv_store_text_chunks.json",
        {
            "file_1-chunk-0": {"content": "[segment_id:seg_1]\n工程师负责系统设计。"},
            "file_1-chunk-1": {"content": "[segment_id:seg_2]\nFastAPI 用于实现服务。"},
        },
    )

    nodes, edges = LightRAGGraphReader(str(tmp_path)).build_lightrag_result_graph(
        entities=[
            {
                "entity_name": "工程师",
                "entity_type": "角色",
                "description": "负责系统设计和实现。",
                "source_id": "file_1-chunk-0",
            }
        ],
        relationships=[
            {
                "src_id": "工程师",
                "tgt_id": "FastAPI",
                "keywords": "使用",
                "description": "工程师使用 FastAPI 构建服务。",
                "weight": 2.5,
                "source_id": "file_1-chunk-0,file_1-chunk-1",
            }
        ],
    )

    assert [node.id for node in nodes] == ["工程师", "FastAPI"]
    assert nodes[0].source_segment_ids == ["seg_1"]
    assert edges[0].source == "工程师"
    assert edges[0].target == "FastAPI"
    assert edges[0].keywords == "使用"
    assert edges[0].weight == 2.5
    assert edges[0].source_segment_ids == ["seg_1", "seg_2"]
