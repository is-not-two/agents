"""V2-b SearchService 向量路径的状态感知接线测试（全链路 mock，不触真实模型/数据库）。"""

from types import SimpleNamespace

import pytest

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.search_service import SearchService
from rag_tech_retriever.rag.retrieval.reranker import RerankedHit
from rag_tech_retriever.rag.vector_store.pgvector_client import SearchHit


def _candidate(chunk_id: str, score: float, status: str) -> SearchHit:
    """向量召回候选。"""
    return SearchHit(
        chunk_id=chunk_id,
        source_file="doc.md",
        heading_path="标题",
        content=f"{chunk_id} 正文",
        status_marker=status,
        similarity=score,
    )


def _service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    status_aware: bool,
) -> SearchService:
    """注入合成配置与向量链路 mock；唯一变量 = retrieval.status_aware。"""
    (tmp_path / "prompts.yaml").write_text("embedding: {query_instruction: ''}\n", encoding="utf-8")
    config = SimpleNamespace(
        settings_path=tmp_path / "settings.yaml",
        get=lambda key, default=None: {
            "vector_store.table_name": "rag_chunks",
            "retrieval.candidate_k": 20,
            "retrieval.top_k": 5,
            "retrieval.status_aware": status_aware,
        }.get(key, default),
        resolve=lambda key: None,  # 全文检索不读真实语料文件
    )
    monkeypatch.setattr(ConfigLoader, "_load_env_file", lambda self: {})
    monkeypatch.setattr(ConfigLoader, "load_default", lambda: config)

    embedder = SimpleNamespace(embed_query=lambda query: [0.1] * 4)
    monkeypatch.setattr(
        "rag_tech_retriever.rag.embedding.bge_embedder.BgeEmbedder",
        SimpleNamespace(from_config=lambda *args, **kwargs: embedder),
    )
    # 重排后：DISABLED 条目以 0.90 排第一，CONFIRMED 0.88 第二（近分竞争场景）
    reranked = [
        RerankedHit(
            chunk_id="disabled-entry",
            source_file="doc.md",
            heading_path="标题D",
            content="占位条目正文",
            status_marker="DISABLED",
            similarity=0.91,
            rerank_score=0.90,
            original_rank=1,
            new_rank=1,
        ),
        RerankedHit(
            chunk_id="confirmed-entry",
            source_file="doc.md",
            heading_path="标题C",
            content="已落地条目正文",
            status_marker="CONFIRMED",
            similarity=0.89,
            rerank_score=0.88,
            original_rank=2,
            new_rank=2,
        ),
    ]
    monkeypatch.setattr(
        "rag_tech_retriever.rag.retrieval.reranker.Reranker",
        SimpleNamespace(from_config=lambda *args, **kwargs: SimpleNamespace(rerank=lambda *a, **k: reranked)),
    )
    # PgVectorClient 以构造函数调用（client = PgVectorClient()），mock 为可调用对象
    monkeypatch.setattr(
        "rag_tech_retriever.rag.vector_store.pgvector_client.PgVectorClient",
        lambda *args, **kwargs: SimpleNamespace(search=lambda *a, **k: reranked, close=lambda: None),
    )
    store = SimpleNamespace(list=lambda kind: [])
    return SearchService(store, connection=SimpleNamespace(load=dict))


def test_status_aware_on_demotes_and_exposes_adjusted_score(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """正常用例：开关开启时 DISABLED 被降权，落地条目反超第一，score 取调整分。"""
    service = _service(monkeypatch, tmp_path, status_aware=True)
    result = service.query("怎么做某事", "docs", "vector")
    assert [hit["id"] for hit in result["hits"]] == ["confirmed-entry", "disabled-entry"]
    by_id = {hit["id"]: hit for hit in result["hits"]}
    assert by_id["disabled-entry"]["score"] == pytest.approx(0.90 * 0.85)
    assert by_id["confirmed-entry"]["score"] == pytest.approx(0.88)
    assert by_id["disabled-entry"]["status_marker"] == "DISABLED"


def test_status_aware_off_keeps_rerank_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """边界用例：开关关闭时保持重排序，score 取重排分（V1.5 口径不变）。"""
    service = _service(monkeypatch, tmp_path, status_aware=False)
    result = service.query("怎么做某事", "docs", "vector")
    assert [hit["id"] for hit in result["hits"]] == ["disabled-entry", "confirmed-entry"]
    assert result["hits"][0]["score"] == pytest.approx(0.90)
