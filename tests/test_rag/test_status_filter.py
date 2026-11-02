"""V2-b 状态感知降权单测：权重生效、只降不加、稳定排序、配置缺省与非法值回退。"""

import pytest

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.retrieval.reranker import RerankedHit
from rag_tech_retriever.rag.retrieval.status_filter import (
    DEFAULT_STATUS_WEIGHTS,
    STATUS_LABELS,
    StatusFilter,
    status_suffix,
)
from rag_tech_retriever.rag.vector_store.pgvector_client import SearchHit


def _reranked(
    chunk_id: str,
    score: float,
    status_marker: str = "UNKNOWN",
    pre_rank: int = 0,
) -> RerankedHit:
    """构造测试用重排命中。"""
    return RerankedHit(
        chunk_id=chunk_id,
        source_file="doc.md",
        heading_path="标题",
        content=f"{chunk_id} 的正文",
        status_marker=status_marker,
        similarity=0.5,
        rerank_score=score,
        original_rank=pre_rank or 1,
        new_rank=pre_rank or 1,
    )


def test_from_config_reads_weights_section() -> None:
    """正常用例：status_weights 从 settings.yaml 读取（与配置中心口径一致）。"""
    filt = StatusFilter.from_config(ConfigLoader.load_default())
    assert filt.weight_for("DISABLED") == pytest.approx(0.85)
    assert filt.weight_for("PENDING") == pytest.approx(0.92)


def test_apply_demotes_only_unlanded_statuses() -> None:
    """正常用例：DISABLED/PENDING 被降权，CONFIRMED/UNKNOWN/EXCEPTION 不动（只降不加）。"""
    hits = [
        _reranked("d", 0.90, "DISABLED"),
        _reranked("p", 0.90, "PENDING"),
        _reranked("c", 0.90, "CONFIRMED"),
        _reranked("u", 0.90, "UNKNOWN"),
        _reranked("e", 0.90, "EXCEPTION"),
    ]
    results = StatusFilter().apply(hits)
    by_id = {hit.chunk_id: hit for hit in results}
    assert by_id["d"].adjusted_score == pytest.approx(0.90 * DEFAULT_STATUS_WEIGHTS["DISABLED"])
    assert by_id["p"].adjusted_score == pytest.approx(0.90 * DEFAULT_STATUS_WEIGHTS["PENDING"])
    for key in ("c", "u", "e"):
        assert by_id[key].adjusted_score == pytest.approx(0.90)
        assert by_id[key].new_rank < by_id["p"].new_rank < by_id["d"].new_rank


def test_apply_swaps_near_tie_but_keeps_clear_winner() -> None:
    """正常用例：近分时落地条目前移；分差明显时降权不改变次序（有界性）。"""
    # 近分：DISABLED 0.90 vs CONFIRMED 0.88 → 0.90*0.85=0.765 < 0.88，落地者反超
    near = StatusFilter().apply(
        [_reranked("disabled", 0.90, "DISABLED"), _reranked("confirmed", 0.88, "CONFIRMED")]
    )
    assert [hit.chunk_id for hit in near] == ["confirmed", "disabled"]
    # 明显分差：DISABLED 0.98 降权后 0.833 仍高于 0.70 → 次序不变（降权不翻盘明显差距）
    clear = StatusFilter().apply(
        [_reranked("disabled", 0.98, "DISABLED"), _reranked("confirmed", 0.70, "CONFIRMED")]
    )
    assert [hit.chunk_id for hit in clear] == ["disabled", "confirmed"]


def test_apply_preserves_ranks_and_is_stable_on_ties() -> None:
    """边界用例：同调整分保持原序；pre_rank/new_rank 完整记录。"""
    hits = [
        _reranked("a", 0.80, "UNKNOWN"),
        _reranked("b", 0.80, "UNKNOWN"),
        _reranked("c", 0.86, "PENDING"),  # 0.86*0.92=0.7916，降权后落到 a/b 之后
    ]
    results = StatusFilter().apply(hits)
    assert [hit.chunk_id for hit in results] == ["a", "b", "c"]
    assert [(hit.pre_rank, hit.new_rank) for hit in results] == [(1, 1), (2, 2), (3, 3)]
    assert results[2].adjusted_score == pytest.approx(0.86 * 0.92)


def test_apply_empty_input_returns_empty() -> None:
    """边界用例：空输入返回空列表。"""
    assert StatusFilter().apply([]) == []


def test_apply_on_vector_hits_uses_similarity() -> None:
    """边界用例：SearchHit（无重排链路）以 similarity 为排序分。"""
    hits = [
        SearchHit(
            chunk_id="d",
            source_file="doc.md",
            heading_path="标题",
            content="正文",
            status_marker="DISABLED",
            similarity=0.60,
        ),
        SearchHit(
            chunk_id="c",
            source_file="doc.md",
            heading_path="标题",
            content="正文",
            status_marker="CONFIRMED",
            similarity=0.55,
        ),
    ]
    results = StatusFilter().apply(hits)
    assert [hit.chunk_id for hit in results] == ["c", "d"]
    assert results[1].adjusted_score == pytest.approx(0.60 * 0.85)


def test_invalid_weights_fall_back_to_identity() -> None:
    """异常用例：非法权重（越界/非数值/布尔）按 1.0 处理；未配置状态回退 1.0。"""
    filt = StatusFilter(weights={"DISABLED": 1.5, "PENDING": -1, "EXCEPTION": True})
    assert filt.weight_for("DISABLED") == 1.0
    assert filt.weight_for("PENDING") == 1.0
    assert filt.weight_for("EXCEPTION") == 1.0
    assert filt.weight_for("不存在的状态") == 1.0


def test_status_suffix_only_for_labelled_markers() -> None:
    """正常用例：状态后缀只对有标签状态生成，UNKNOWN/PERSONAL 不标注。"""
    assert status_suffix("PENDING") == "（状态：待接入/待注册）"
    assert status_suffix("DISABLED") == "（状态：占位/不分配）"
    assert status_suffix("UNKNOWN") == ""
    assert status_suffix("PERSONAL") == ""
    assert status_suffix(None) == ""
    assert set(STATUS_LABELS) >= {"CONFIRMED", "PENDING", "DISABLED", "EXCEPTION", "UNKNOWN"}
