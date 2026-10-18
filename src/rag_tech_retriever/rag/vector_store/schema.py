"""pgvector 建表 / 索引 / 检索 SQL 生成：向量维度、表名全部来自配置，禁止硬编码。

背景：pgvector 建表后维度不可逆（更换模型必须重建表重灌数据），因此维度必须抽成配置项
（项目坑点之一）；本模块的 DDL 全部由参数生成，维度变化时无需改代码。

阶段：V1。
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: pgvector 的 ivfflat 索引维度上限
MAX_INDEX_DIM = 2000


class SchemaError(Exception):
    """表名 / 维度等参数校验失败。"""


def validate_table_name(table_name: str) -> str:
    """校验表名（防注入：仅允许字母数字下划线且不以数字开头）。"""
    if not _IDENTIFIER_RE.match(table_name):
        raise SchemaError(f"非法表名：{table_name!r}")
    return table_name


def validate_dim(dim: int) -> int:
    """校验向量维度（正整数且不超过 ivfflat 索引上限）。"""
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        raise SchemaError(f"非法向量维度：{dim!r}")
    if dim > MAX_INDEX_DIM:
        raise SchemaError(f"向量维度 {dim} 超过 ivfflat 索引上限 {MAX_INDEX_DIM}")
    return dim


def build_create_table_sql(table_name: str, dim: int) -> str:
    """生成建表 SQL（幂等：IF NOT EXISTS）。"""
    table = validate_table_name(table_name)
    dimension = validate_dim(dim)
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
    namespace     TEXT NOT NULL DEFAULT 'tech_doc',
    chunk_id      TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    heading_path  TEXT NOT NULL,
    content       TEXT NOT NULL,
    status_marker TEXT NOT NULL DEFAULT 'UNKNOWN',
    embedding     vector({dimension}) NOT NULL,
    PRIMARY KEY (namespace, chunk_id)
)
""".strip()


def build_create_index_sql(
    table_name: str, lists: int = 10, index_type: str = "ivfflat"
) -> str:
    """生成 IVFFlat 索引 SQL（应在数据入库后执行：空表建索引无意义）。"""
    table = validate_table_name(table_name)
    if index_type == "exact":
        return ""
    if index_type != "ivfflat":
        raise SchemaError(f"不支持的索引类型：{index_type!r}")
    if not isinstance(lists, int) or lists <= 0:
        raise SchemaError(f"非法 lists：{lists!r}")
    return (
        f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding "
        f"ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
    )


def build_upsert_sql(table_name: str) -> str:
    """生成 upsert SQL（按 chunk_id 幂等写入，配合 execute_values 使用）。"""
    table = validate_table_name(table_name)
    return f"""
INSERT INTO {table} (namespace, chunk_id, source_file, heading_path, content, status_marker, embedding)
VALUES %s
ON CONFLICT (namespace, chunk_id) DO UPDATE SET
    source_file = EXCLUDED.source_file,
    heading_path = EXCLUDED.heading_path,
    content = EXCLUDED.content,
    status_marker = EXCLUDED.status_marker,
    embedding = EXCLUDED.embedding
""".strip()


def build_search_sql(table_name: str) -> str:
    """生成相似度检索 SQL（cosine：similarity = 1 - 距离，越大越相似）。"""
    table = validate_table_name(table_name)
    return f"""
SELECT chunk_id, source_file, heading_path, content, status_marker,
       1 - (embedding <=> %s::vector) AS similarity, namespace
FROM {table}
WHERE namespace = %s
ORDER BY embedding <=> %s::vector
LIMIT %s
""".strip()


def build_count_sql(table_name: str) -> str:
    """生成计数 SQL。"""
    table = validate_table_name(table_name)
    return f"SELECT COUNT(*) FROM {table} WHERE namespace = %s"


def validate_namespace(namespace: str) -> str:
    """拒绝空域和非法标识；实际查询仍使用参数绑定。"""
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", namespace):
        raise SchemaError(f"非法 namespace：{namespace!r}")
    return namespace
