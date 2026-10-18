"""bge-base-zh-v1.5 嵌入模型封装：内置 query 侧 instruction 前缀逻辑（passage 侧不加）。

关键约定（中文非对称检索，项目坑点之一）:
- passage（文档侧）编码不加任何前缀；
- query（查询侧）编码默认加官方 instruction 前缀（配置于 prompts.yaml）；
- ``with_instruction=False`` 可关闭 query 前缀——这是 V1 对照实验的唯一变量。

模型懒加载：首次调用时才下载/载入模型；国内网络可设置 HF_ENDPOINT=https://hf-mirror.com。

阶段：V1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Sequence

from rag_tech_retriever.common.config_loader import ConfigLoader

#: 官方推荐的 query 前缀（配置缺失时的兜底，配置优先）
DEFAULT_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class EmbeddingError(Exception):
    """嵌入模型加载或编码失败。"""


@dataclass
class BgeEmbedder:
    """bge 中文嵌入模型封装。

    Attributes:
        model_name: 模型名（默认 bge-base-zh-v1.5）。
        device: 运行设备（cpu / cuda）。
        normalize: 是否归一化向量（归一化后配合 cosine 距离使用）。
        batch_size: passage 批量编码大小。
        query_instruction: query 侧 instruction 前缀。
        with_instruction: 是否启用 query 前缀（V1 对照实验开关）。
    """

    model_name: str = "bge-base-zh-v1.5"
    device: str = "cpu"
    normalize: bool = True
    batch_size: int = 32
    query_instruction: str = DEFAULT_QUERY_INSTRUCTION
    with_instruction: bool = True
    _model: Any = field(default=None, init=False, repr=False)

    @classmethod
    def from_config(
        cls,
        settings: ConfigLoader,
        prompts: ConfigLoader,
        with_instruction: bool = True,
    ) -> "BgeEmbedder":
        """从配置构建：模型参数读 settings.yaml，前缀读 prompts.yaml。

        Args:
            settings: settings.yaml 加载器。
            prompts: prompts.yaml 加载器。
            with_instruction: 是否对 query 加 instruction 前缀。

        Returns:
            BgeEmbedder 实例。
        """
        return cls(
            model_name=str(settings.get("embedding.model_name", "bge-base-zh-v1.5")),
            device=str(settings.get("embedding.device", "cpu")),
            normalize=bool(settings.get("embedding.normalize", True)),
            batch_size=int(settings.get("embedding.batch_size", 32)),
            query_instruction=str(
                prompts.get("embedding.query_instruction", DEFAULT_QUERY_INSTRUCTION)
            ),
            with_instruction=with_instruction,
        )

    def _ensure_model(self) -> Any:
        """懒加载 sentence-transformers 模型（首次触发模型下载）。"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    '未安装 sentence-transformers，请执行 pip install -e ".[rag]"'
                ) from exc
            try:
                self._model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as exc:
                raise EmbeddingError(
                    f"加载模型失败：{self.model_name}（{exc}）；"
                    "国内网络可设置 HF_ENDPOINT=https://hf-mirror.com 后重试"
                ) from exc
        return self._model

    def text_for_query(self, query: str) -> str:
        """按开关拼接 query 编码文本（便于单测与实验记录）。"""
        if self.with_instruction and self.query_instruction:
            return f"{self.query_instruction}{query}"
        return query

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        """passage 侧批量编码（不加任何前缀）。

        Args:
            texts: 文档片段文本列表。

        Returns:
            与输入等长的向量列表。
        """
        model = self._ensure_model()
        vectors = model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]

    def embed_query(self, query: str) -> List[float]:
        """query 侧编码：按 with_instruction 决定是否加 instruction 前缀。

        Args:
            query: 用户查询文本。

        Returns:
            查询向量。
        """
        model = self._ensure_model()
        vector = model.encode(
            [self.text_for_query(query)],
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )[0]
        return [float(value) for value in vector]