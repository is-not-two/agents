"""pgvector 客户端：连接、批量写入、相似度检索（psycopg2 + psycopg2.extras）。

连接信息一律通过环境变量传入（POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB /
POSTGRES_USER / POSTGRES_PASSWORD，见 .env.example），禁止写入配置文件（敏感信息规范）。

阶段：V1。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.vector_store.schema import (
    build_count_sql,
    build_create_index_sql,
    build_create_table_sql,
    build_search_sql,
    build_upsert_sql,
    validate_namespace,
)


class VectorStoreError(Exception):
    """向量库连接或读写失败。"""


def to_vector_literal(vector: Sequence[float]) -> str:
    """把浮点序列转成 pgvector 字面量字符串 "[0.1,0.2,...]"。"""
    return "[" + ",".join(f"{float(value):.6f}" for value in vector) + "]"


@dataclass
class SearchHit:
    """一次检索命中结果。"""

    chunk_id: str
    source_file: str
    heading_path: str
    content: str
    status_marker: str
    similarity: float
    namespace: str = "tech_doc"


class PgVectorClient:
    """pgvector 连接与 CRUD 封装。"""

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        dbname: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        """初始化连接参数（未显式传入时从环境变量 / .env 读取）。

        Args:
            host: 数据库主机；None 时读 POSTGRES_HOST。
            port: 端口；None 时读 POSTGRES_PORT。
            dbname: 库名；None 时读 POSTGRES_DB。
            user: 用户；None 时读 POSTGRES_USER。
            password: 密码；None 时读 POSTGRES_PASSWORD。
        """
        config = ConfigLoader.load_default()
        self.host = host or str(config.env("POSTGRES_HOST", "127.0.0.1"))
        self.port = port or str(config.env("POSTGRES_PORT", "5432"))
        self.dbname = dbname or str(config.env("POSTGRES_DB", "rag_tech_doc"))
        self.user = user or str(config.env("POSTGRES_USER", "rag"))
        self.password = password or str(config.env("POSTGRES_PASSWORD", ""))
        self._conn: Any = None

    def connect(self) -> None:
        """建立连接（autocommit；DDL / DML 立即生效）。"""
        if self._conn is not None:
            return
        try:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                connect_timeout=10,
            )
            self._conn.autocommit = True
        except psycopg2.Error as exc:
            raise VectorStoreError(
                f"连接 PostgreSQL 失败（{self.host}:{self.port}/{self.dbname}）：{exc}"
            ) from exc

    def close(self) -> None:
        """关闭连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        """执行一条无返回值的 SQL。"""
        self.connect()
        try:
            cursor = self._conn.cursor()
            with cursor:
                cursor.execute(sql, params)
        except psycopg2.Error as exc:
            raise VectorStoreError(f"SQL 执行失败：{exc}") from exc

    def fetch_scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        """执行 SQL 并返回第一行第一列。"""
        self.connect()
        try:
            cursor = self._conn.cursor()
            with cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row[0] if row else None
        except psycopg2.Error as exc:
            raise VectorStoreError(f"SQL 查询失败：{exc}") from exc

    def fetch_all(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        """执行 SQL 并返回全部行为字典列表（列名为键）。"""
        self.connect()
        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as exc:
            raise VectorStoreError(f"SQL 查询失败：{exc}") from exc

    def create_extension(self) -> None:
        """创建 vector 扩展（需要超级用户权限；docker 部署默认满足）。"""
        self.execute("CREATE EXTENSION IF NOT EXISTS vector")

    def create_table(self, table_name: str, dim: int) -> None:
        """按配置维度建表（幂等）。"""
        self.execute(build_create_table_sql(table_name, dim))

    def create_index(
        self, table_name: str, lists: int = 10, index_type: str = "ivfflat"
    ) -> None:
        """建 IVFFlat 索引（数据入库后执行）。"""
        sql = build_create_index_sql(table_name, lists, index_type)
        if sql:
            self.execute(sql)

    def count(self, table_name: str, namespace: str = "tech_doc") -> int:
        """统计表中记录数。"""
        return int(self.fetch_scalar(build_count_sql(table_name), (validate_namespace(namespace),)))

    def upsert_chunks(
        self,
        table_name: str,
        rows: Sequence[dict[str, Any]],
        batch_size: int = 64,
        namespace: str = "tech_doc",
    ) -> int:
        """批量 upsert。

        Args:
            table_name: 表名。
            rows: 每项需含 chunk_id / source_file / heading_path / content /
                status_marker / embedding。
            batch_size: execute_values 的页大小。
            namespace: 目标命名空间（主键组成部分）。

        Returns:
            写入的记录条数。
        """
        namespace = validate_namespace(namespace)
        if any(row.get("namespace", namespace) != namespace for row in rows):
            raise VectorStoreError("批次中存在与目标 namespace 不一致的记录")
        self.connect()
        sql = build_upsert_sql(table_name)
        values = [
            (
                namespace,
                row["chunk_id"],
                row["source_file"],
                row["heading_path"],
                row["content"],
                row["status_marker"],
                to_vector_literal(row["embedding"]),
            )
            for row in rows
        ]
        try:
            cursor = self._conn.cursor()
            with cursor:
                psycopg2.extras.execute_values(cursor, sql, values, page_size=batch_size)
        except psycopg2.Error as exc:
            raise VectorStoreError(f"批量写入失败：{exc}") from exc
        return len(values)

    def search(
        self,
        table_name: str,
        query_vector: Sequence[float],
        top_k: int,
        namespace: str = "tech_doc",
    ) -> list[SearchHit]:
        """cosine 相似度检索 top_k。

        Args:
            table_name: 表名。
            query_vector: 查询向量。
            top_k: 返回条数。
            namespace: 命名空间过滤。

        Returns:
            SearchHit 列表，按相似度降序。
        """
        namespace = validate_namespace(namespace)
        if top_k <= 0:
            return []
        self.connect()
        sql = build_search_sql(table_name)
        literal = to_vector_literal(query_vector)
        try:
            cursor = self._conn.cursor()
            with cursor:
                cursor.execute(sql, (literal, namespace, literal, top_k))
                records = cursor.fetchall()
        except psycopg2.Error as exc:
            raise VectorStoreError(f"检索失败：{exc}") from exc
        return [
            SearchHit(
                chunk_id=row[0],
                source_file=row[1],
                heading_path=row[2],
                content=row[3],
                status_marker=row[4],
                similarity=float(row[5]),
                namespace=row[6],
            )
            for row in records
        ]
