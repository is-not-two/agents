"""协议号精准查询工具（命令/事件定义与参数）。

在技术文档向量库（pgvector 表）上做只读 ILIKE 精准/包含匹配：
协议号命中 h2 标题或正文即返回该 chunk 的定位信息与摘要。
连接信息沿用 PgVectorClient 的环境变量约定。
"""

from __future__ import annotations

from rag_tech_retriever.rag.vector_store.pgvector_client import (
    PgVectorClient,
    VectorStoreError,
)
from rag_tech_retriever.rag.vector_store.schema import (
    validate_namespace,
    validate_table_name,
)

_MAX_NUMBER = 64
_EXCERPT = 400


def protocol_query(
    number: str,
    limit: int = 5,
    table_name: str = "rag_chunks",
    namespace: str = "tech_doc",
) -> dict:
    """按协议号查询语料定义片段；number 支持 h2/正文包含匹配。"""
    if not isinstance(number, str):
        raise TypeError("number 必须是字符串")
    cleaned = number.strip()
    if not cleaned or len(cleaned) > _MAX_NUMBER:
        raise ValueError("协议号不能为空且不超过 64 字符")
    # 去除通配符，避免用户输入改写匹配语义
    for wildcard in ("%", "_"):
        cleaned = cleaned.replace(wildcard, " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        raise ValueError("协议号去除通配符后为空")
    limit = max(1, min(int(limit), 20))
    table_name = validate_table_name(table_name)
    namespace = validate_namespace(namespace)

    sql = (
        f"SELECT chunk_id, source_file, heading_path, content, status_marker "
        f"FROM {table_name} "
        "WHERE namespace = %s AND (heading_path ILIKE %s OR content ILIKE %s) "
        "ORDER BY chunk_id LIMIT %s"
    )
    pattern = f"%{cleaned}%"
    try:
        client = PgVectorClient()
        try:
            client.connect()
            rows = client.fetch_all(sql, (namespace, pattern, pattern, limit))
        finally:
            client.close()
    except VectorStoreError as exc:
        raise RuntimeError(f"向量库暂不可用：{exc}") from exc

    return {
        "number": cleaned,
        "namespace": namespace,
        "count": len(rows),
        "matches": [
            {
                "chunk_id": row["chunk_id"],
                "source_file": row.get("source_file", ""),
                "heading_path": row.get("heading_path", ""),
                "excerpt": str(row.get("content", ""))[:_EXCERPT],
                "status_marker": row.get("status_marker"),
            }
            for row in rows
        ],
    }
