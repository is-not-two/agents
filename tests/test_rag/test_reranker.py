"""V1.5 重排模块单测：重排正确性、边界（空池 / top_k 超界 / 同分稳定）、异常（打分数量不匹配）。"""

from collections.abc import Sequence

import pytest

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.retrieval.reranker import Reranker, RerankerError
from rag_tech_retriever.rag.vector_store.pgvector_client import SearchHit


def _hit(chunk_id: str, similarity: float = 0.5) -> SearchHit:
    """构造测试用检索命中。"""
    return SearchHit(
        chunk_id=chunk_id,
        source_file="doc.md",
        heading_path="一级标题 > 二级标题",
        content=f"{chunk_id} 的正文内容",
        status_marker="",
        similarity=similarity,
    )


def test_from_config_reads_reranker_section() -> None:
    """正常用例：reranker 配置从 settings.yaml 读取。"""
    reranker = Reranker.from_config(ConfigLoader.load_default())
    assert reranker.model_name == "BAAI/bge-reranker-base"
    assert reranker.device == "cpu"


def test_rerank_reorders_and_tracks_ranks() -> None:
    """正常用例：按注入 scorer 的分数重排，记录重排前后排名（模拟「排序靠后」被救回）。"""
    captured: dict[str, object] = {}

    def scorer(query: str, texts: Sequence[str]) -> list[float]:
        captured["query"] = query
        captured["texts"] = list(texts)
        # 候选池第 3 位分数最高，应被提到第 1 位
        return [0.2, 0.1, 0.9]

    hits = [_hit("chunk-1"), _hit("chunk-2"), _hit("chunk-3")]
    reranker = Reranker(scorer=scorer)
    results = reranker.rerank("查询文本", hits, top_k=2)

    assert [item.chunk_id for item in results] == ["chunk-3", "chunk-1"]
    assert [item.new_rank for item in results] == [1, 2]
    assert [item.original_rank for item in results] == [3, 1]
    assert results[0].rerank_score == 0.9
    assert captured["query"] == "查询文本"
    assert captured["texts"] == [f"chunk-{index} 的正文内容" for index in (1, 2, 3)]


def test_rerank_empty_pool_does_not_call_scorer() -> None:
    """边界用例：空候选池直接返回空列表，不触发打分（不加载模型）。"""

    def scorer(query: str, texts: Sequence[str]) -> list[float]:
        raise AssertionError("空候选池不应调用 scorer")

    reranker = Reranker(scorer=scorer)
    assert reranker.rerank("查询", [], top_k=5) == []


def test_rerank_top_k_exceeds_pool_returns_all() -> None:
    """边界用例：top_k 超过候选数时返回全部（不补空位）。"""
    reranker = Reranker(scorer=lambda query, texts: [0.5, 0.6])
    results = reranker.rerank("查询", [_hit("a"), _hit("b")], top_k=5)
    assert [item.chunk_id for item in results] == ["b", "a"]


def test_rerank_top_k_non_positive_returns_empty() -> None:
    """边界用例：top_k <= 0 返回空列表。"""
    reranker = Reranker(scorer=lambda query, texts: [0.5])
    assert reranker.rerank("查询", [_hit("a")], top_k=0) == []


def test_rerank_tie_keeps_pool_order() -> None:
    """边界用例：同分时保持候选池原顺序（稳定排序，结果可复现）。"""
    reranker = Reranker(scorer=lambda query, texts: [0.5, 0.5, 0.5])
    results = reranker.rerank("查询", [_hit("a"), _hit("b"), _hit("c")], top_k=3)
    assert [item.chunk_id for item in results] == ["a", "b", "c"]


def test_rerank_score_count_mismatch_raises() -> None:
    """异常用例：scorer 返回数量与候选数不一致时抛 RerankerError。"""
    reranker = Reranker(scorer=lambda query, texts: [0.5])
    with pytest.raises(RerankerError):
        reranker.rerank("查询", [_hit("a"), _hit("b")], top_k=2)