"""V1：批量向量化入库（corpus.jsonl → pgvector）。

流程：读语料 → bge passage 侧编码（不加任何前缀）→ upsert 入库 → 建 IVFFlat 索引 → 打印统计。

单变量约束：query 侧 instruction 前缀是 V1 对照实验的变量，只作用于检索侧
（v1_run_baseline.py）；passage 侧按 bge 官方约定不加前缀，本脚本固定该行为。

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v1_embed_and_index.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient


def load_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    """读取 corpus.jsonl，返回记录列表。"""
    records: list[dict[str, Any]] = []
    with corpus_path.open(encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                records.append(json.loads(line))
    return records


def main() -> None:
    """脚本入口：加载 → 编码 → 入库 → 建索引 → 打印统计。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")

    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    declared_dim = int(config.get("embedding.dim", 768))
    corpus_path = config.resolve("paths.corpus_jsonl")
    if corpus_path is None or not corpus_path.is_file():
        raise SystemExit(f"语料文件不存在：{corpus_path}（请先运行 scripts/ingest_md.py）")

    records = load_corpus(corpus_path)
    print(f"语料：{corpus_path.relative_to(config.settings_path.parents[1])}（{len(records)} 条）")

    embedder = BgeEmbedder.from_config(config, prompts, with_instruction=True)
    print(f"模型：{embedder.model_name}（device={embedder.device}，passage 侧不加前缀）")

    started = time.perf_counter()
    vectors = embedder.embed_passages([record["content"] for record in records])
    elapsed = time.perf_counter() - started
    if not vectors:
        raise SystemExit("编码结果为空，请检查语料文件")

    actual_dim = len(vectors[0])
    print(f"编码完成：{len(vectors)} 条，用时 {elapsed:.1f}s，向量维度 {actual_dim}")
    if actual_dim != declared_dim:
        raise SystemExit(
            f"模型输出维度 {actual_dim} 与配置 embedding.dim={declared_dim} 不一致；"
            "pgvector 维度不可逆，请先修正配置并重建表（scripts/v1_init_vector_db.py）"
        )

    rows = [
        {
            "chunk_id": record["chunk_id"],
            "source_file": record["source_file"],
            "heading_path": record["heading_path"],
            "content": record["content"],
            "status_marker": record["meta"]["status_marker"],
            "embedding": vector,
        }
        for record, vector in zip(records, vectors)
    ]

    client = PgVectorClient()
    try:
        written = client.upsert_chunks(table_name, rows)
        index_lists = int(config.get("vector_store.index.lists", 10))
        index_type = str(config.get("vector_store.index.type", "exact"))
        client.create_index(table_name, index_lists, index_type=index_type)
        total = client.count(table_name)
        print("=" * 72)
        print("V1 向量入库完成")
        print("=" * 72)
        print(f"写入：{written} 条 | tech_doc 总数：{total} 条 | 索引方式={index_type}")
        print("下一步：.venv/Scripts/python.exe scripts/v1_run_baseline.py")
    finally:
        client.close()


if __name__ == "__main__":
    main()
