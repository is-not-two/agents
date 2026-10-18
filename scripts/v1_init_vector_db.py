"""V1：初始化向量数据库表结构（维度读取 config/settings.yaml，不硬编码）。

流程：连接 → CREATE EXTENSION vector → 按配置维度建表 → 打印确认信息。
幂等：重复执行安全（IF NOT EXISTS）。

注意：IVFFlat 索引由 v1_embed_and_index.py 在数据入库后创建（空表建索引无意义）。

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v1_init_vector_db.py
"""

from __future__ import annotations

import sys

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient


def main() -> None:
    """脚本入口：建扩展 → 建表 → 打印确认。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    config = ConfigLoader.load_default()
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    dim = int(config.get("embedding.dim", 768))

    client = PgVectorClient()
    try:
        client.create_extension()
        client.create_table(table_name, dim)
        print("=" * 72)
        print("V1 向量库初始化完成")
        print("=" * 72)
        print(f"连接：{client.host}:{client.port}/{client.dbname}（user={client.user}）")
        print(f"表：{table_name}（embedding vector({dim})，维度来自 config/settings.yaml）")
        print("下一步：.venv/Scripts/python.exe scripts/v1_embed_and_index.py")
    finally:
        client.close()


if __name__ == "__main__":
    main()