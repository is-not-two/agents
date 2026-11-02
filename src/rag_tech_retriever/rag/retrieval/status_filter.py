"""业务状态感知降权：检索排序后按 meta.status_marker 做有界乘法降权。

阶段：V2-b。

背景（真实业务坑）：文档里有协议条目不代表能力已落地——「命令已注册、号段需
客户端确认」「占位、不 dispatch」的条目与已落地条目在纯相关性排序里同等竞争，
用户问「X 能不能用」时可能先看到未落地条目。本模块在重排之后追加一次排序调整：
状态为「未落地」的条目按配置权重缩放排序分，同分保持原序。

设计要点
- 只降权不加权：CONFIRMED / UNKNOWN / EXCEPTION 权重恒为 1.0。语料中 206/237
  条无状态标记（UNKNOWN），惩罚无标记条目会伤及一般检索；EXCEPTION 是「走
  特殊通道」的落地决策记录（内容本身已落地），不是未落地信号；
- 权重配置化：settings.yaml ``retrieval.status_weights``，缺省键回退 1.0，
  不存在的状态键同样回退 1.0（配置缺失不致命）；
- 稳定排序：同调整分保持原序（与 Reranker 口径一致，结果可复现）；
- 保留前后排名：逐条记录 pre_rank / new_rank，供实验报告逐题归因；
- 可整体关闭：``retrieval.status_aware=false`` 时不启用（V2-b 实验的开关变量，
  由评测守护指标决定默认值；2026-10-25 实测为负结果，默认 false）。

用法
    from rag_tech_retriever.common.config_loader import ConfigLoader
    from rag_tech_retriever.rag.retrieval.status_filter import StatusFilter

    filt = StatusFilter.from_config(ConfigLoader.load_default())
    adjusted = filt.apply(reranked_hits)   # RerankedHit 列表 → StatusAdjustedHit 列表
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rag_tech_retriever.common.config_loader import ConfigLoader

#: 未落地状态的默认降权系数（配置可覆盖；未列出的状态一律 1.0）
DEFAULT_STATUS_WEIGHTS: dict[str, float] = {
    "DISABLED": 0.85,
    "PENDING": 0.92,
}

#: 状态 → 人读标签（回答引用上下文与前端展示用；空串 = 不标注）
STATUS_LABELS: dict[str, str] = {
    "CONFIRMED": "已确认落地",
    "PENDING": "待接入/待注册",
    "DISABLED": "占位/不分配",
    "EXCEPTION": "特殊通道决策",
    "UNKNOWN": "",
}


def status_suffix(status_marker: object) -> str:
    """把业务状态标记转成引用上下文的状态后缀（无标注状态返回空串）。

    Args:
        status_marker: 业务状态标记（可为 None / PERSONAL 等非标准值）。

    Returns:
        形如「（状态：待接入/待注册）」的后缀；无标签状态返回空串。
    """
    label = STATUS_LABELS.get(str(status_marker or ""), "")
    return f"（状态：{label}）" if label else ""


@dataclass
class StatusAdjustedHit:
    """状态降权后的单条命中（保留调整前后排名，便于逐题归因）。

    Attributes:
        chunk_id: 切片 id。
        source_file: 来源文件。
        heading_path: 标题层级路径。
        content: 切片正文。
        status_marker: 业务状态标记。
        similarity: 向量检索相似度。
        rerank_score: 重排打分（非重排链路等于 similarity）。
        adjusted_score: 状态降权后的排序分（重排链路的最终排序依据）。
        pre_rank: 调整前排名（1 起）。
        new_rank: 调整后排名（1 起）。
    """

    chunk_id: str
    source_file: str
    heading_path: str
    content: str
    status_marker: str
    similarity: float
    rerank_score: float
    adjusted_score: float
    pre_rank: int
    new_rank: int


class StatusFilter:
    """按 status_marker 对已排序命中做有界降权（稳定排序）。"""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """初始化。

        Args:
            weights: 状态 → 降权系数（<=0 或 >1 的非法值按 1.0 处理）；
                None 使用 DEFAULT_STATUS_WEIGHTS。
        """
        self.weights = dict(DEFAULT_STATUS_WEIGHTS if weights is None else weights)
        for key, value in self.weights.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 1:
                self.weights[key] = 1.0

    @classmethod
    def from_config(cls, settings: ConfigLoader) -> StatusFilter:
        """从 settings.yaml 构建（retrieval.status_weights）。

        Args:
            settings: settings.yaml 加载器。

        Returns:
            StatusFilter 实例（配置缺失时用默认权重）。
        """
        raw = settings.get("retrieval.status_weights", DEFAULT_STATUS_WEIGHTS)
        weights = raw if isinstance(raw, dict) else {}
        return cls(weights={str(k): float(v) for k, v in weights.items()})

    def weight_for(self, status_marker: str) -> float:
        """查询单个状态的降权系数（未配置状态返回 1.0）。

        Args:
            status_marker: 业务状态标记。

        Returns:
            降权系数（0 < w <= 1）。
        """
        return float(self.weights.get(status_marker, 1.0))

    def apply(self, hits: Sequence) -> list[StatusAdjustedHit]:
        """对已排序命中列表做状态降权重排。

        输入可以是 RerankedHit（重排链路，取 rerank_score）或 SearchHit
        （向量直排链路，取 similarity）；两者都须携带 status_marker 与内容字段。

        Args:
            hits: 已按排序分降序的命中序列。

        Returns:
            StatusAdjustedHit 列表（按调整分降序，同分保持原序）；
            空输入返回空列表。
        """
        if not hits:
            return []
        scored: list[tuple[float, int, StatusAdjustedHit]] = []
        for pre_rank, hit in enumerate(hits, start=1):
            rerank_score = float(getattr(hit, "rerank_score", None) or 0.0)
            similarity = float(getattr(hit, "similarity", 0.0) or 0.0)
            base_score = rerank_score if rerank_score else similarity
            status_marker = str(getattr(hit, "status_marker", "UNKNOWN") or "UNKNOWN")
            weight = self.weight_for(status_marker)
            scored.append(
                (
                    base_score * weight,
                    pre_rank,
                    StatusAdjustedHit(
                        chunk_id=hit.chunk_id,
                        source_file=hit.source_file,
                        heading_path=hit.heading_path,
                        content=hit.content,
                        status_marker=status_marker,
                        similarity=similarity,
                        rerank_score=rerank_score,
                        adjusted_score=base_score * weight,
                        pre_rank=pre_rank,
                        new_rank=0,
                    ),
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = [item[2] for item in scored]
        for new_rank, hit in enumerate(results, start=1):
            hit.new_rank = new_rank
        return results
