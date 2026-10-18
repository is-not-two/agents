"""重排算法（候选池 → 精排）。

阶段：V1.5。

V1 基线的失败点为「排序靠后」（锚点在向量召回中排 top-5 之外）。
本模块为对应优化：向量检索先取候选池（retrieval.candidate_k），
再用 CrossEncoder（BAAI/bge-reranker-base）对 (query, passage) 逐对打分，
按分数降序重排后取 top_k——向量库、切片、评测集均不变（单变量原则）。

设计要点
- 模型懒加载：首次 rerank 调用时才下载/载入；空候选池不触发加载；
- scorer 可注入：便于离线单测（不依赖模型下载）；
- 打分数量强校验：scorer 返回值与候选数不一致时直接报错，避免静默错序。

排序口径
- 同分时保持候选池原顺序（稳定排序，结果可复现）；
- top_k 超过候选数时返回全部（不补空位）。

用法
    from rag_tech_retriever.common.config_loader import ConfigLoader
    from rag_tech_retriever.rag.retrieval.reranker import Reranker

    reranker = Reranker.from_config(ConfigLoader.load_default())
    top5 = reranker.rerank(query, candidate_hits, top_k=5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.vector_store.pgvector_client import SearchHit

#: 默认重排模型（配置缺失时的兜底，配置优先）
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"

#: 打分函数签名：(query, 候选文本列表) -> 与候选等长的分数列表
ScoreFn = Callable[[str, Sequence[str]], List[float]]


class RerankerError(Exception):
    """重排模型加载或打分失败。"""


@dataclass
class RerankedHit:
    """重排后的单条命中（保留重排前后排名，便于逐题归因）。

    Attributes:
        chunk_id: 切片 id。
        source_file: 来源文件。
        heading_path: 标题层级路径。
        content: 切片正文。
        status_marker: 业务状态标记（V2-b 起使用）。
        similarity: 向量检索相似度（重排前排序依据）。
        rerank_score: CrossEncoder 打分（重排排序依据）。
        original_rank: 候选池内原排名（1 起）。
        new_rank: 重排后排名（1 起）。
    """

    chunk_id: str
    source_file: str
    heading_path: str
    content: str
    status_marker: str
    similarity: float
    rerank_score: float
    original_rank: int
    new_rank: int


class Reranker:
    """CrossEncoder 重排器：对向量召回候选池做 (query, passage) 精排。"""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        device: str = "cpu",
        scorer: Optional[ScoreFn] = None,
    ) -> None:
        """初始化（不加载模型）。

        Args:
            model_name: CrossEncoder 模型名（HF 仓库 id）。
            device: 运行设备（cpu / cuda）。
            scorer: 可注入打分函数；None 时懒加载 sentence-transformers 模型。
        """
        self.model_name = model_name
        self.device = device
        self._scorer = scorer
        self._model: Any = None

    @classmethod
    def from_config(cls, settings: ConfigLoader) -> "Reranker":
        """从 settings.yaml 构建（reranker.model_name / reranker.device）。

        Args:
            settings: settings.yaml 加载器。

        Returns:
            Reranker 实例。
        """
        return cls(
            model_name=str(settings.get("reranker.model_name", DEFAULT_RERANKER_MODEL)),
            device=str(settings.get("reranker.device", "cpu")),
        )

    def _ensure_scorer(self) -> ScoreFn:
        """懒加载 CrossEncoder 并包装为打分函数（首次触发模型下载）。"""
        if self._scorer is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RerankerError(
                    '未安装 sentence-transformers，请执行 pip install -e ".[rag]"'
                ) from exc
            try:
                self._model = CrossEncoder(self.model_name, device=self.device)
            except Exception as exc:
                raise RerankerError(
                    f"加载重排模型失败：{self.model_name}（{exc}）；"
                    "国内网络可设置 HF_ENDPOINT=https://hf-mirror.com 后重试"
                ) from exc
            model = self._model
            self._scorer = lambda query, texts: [
                float(score) for score in model.predict([(query, text) for text in texts])
            ]
        return self._scorer

    def score(self, query: str, texts: Sequence[str]) -> List[float]:
        """对 (query, 文本) 逐对打分。

        Args:
            query: 查询文本。
            texts: 候选文本列表。

        Returns:
            与 texts 等长的分数列表。

        Raises:
            RerankerError: 打分数量与候选数不一致（防静默错序）。
        """
        scorer = self._ensure_scorer()
        scores = [float(score) for score in scorer(query, list(texts))]
        if len(scores) != len(texts):
            raise RerankerError(
                f"打分数量不匹配：scorer 返回 {len(scores)} 个，候选文本 {len(texts)} 条"
            )
        return scores

    def rerank(
        self,
        query: str,
        hits: Sequence[SearchHit],
        top_k: int,
    ) -> List[RerankedHit]:
        """候选池重排：打分 → 降序（同分保持原序）→ 取 top_k。

        Args:
            query: 查询文本。
            hits: 向量检索候选池（按相似度降序）。
            top_k: 重排后截取条数；超过候选数时返回全部。

        Returns:
            重排后的命中列表（含重排前后排名）；空候选池或 top_k <= 0 返回空列表。
        """
        if not hits or top_k <= 0:
            return []
        scores = self.score(query, [hit.content for hit in hits])
        order = sorted(range(len(hits)), key=lambda index: (-scores[index], index))
        results: List[RerankedHit] = []
        for new_rank, index in enumerate(order[:top_k], start=1):
            hit = hits[index]
            results.append(
                RerankedHit(
                    chunk_id=hit.chunk_id,
                    source_file=hit.source_file,
                    heading_path=hit.heading_path,
                    content=hit.content,
                    status_marker=hit.status_marker,
                    similarity=hit.similarity,
                    rerank_score=scores[index],
                    original_rank=index + 1,
                    new_rank=new_rank,
                )
            )
        return results