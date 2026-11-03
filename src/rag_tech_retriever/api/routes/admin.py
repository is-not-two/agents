"""管理接口：工作台聚合统计与运行状况。

单用户本地模式：鉴权沿用全局令牌中间件（配置令牌后 /api/* 一体保护）。
所有字段只读；向量统计在数据库不可用时显式降级，不冒充可用。
"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.platform.record_store import WORKSPACE_KINDS, StorageError


def create_router(context: WorkspaceContext) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])
    store = context.store
    journal = context.journal
    search = context.search

    def vector_stats() -> dict:
        """向量库条数；连接或查询失败时返回明确的不可用原因。"""
        try:
            from rag_tech_retriever.rag.vector_store.pgvector_client import (
                PgVectorClient,
                VectorStoreError,
            )

            # 向量表名在 settings.yaml（vector_store 段），不在 web.yaml
            table = context.settings.get("vector_store.table_name", "rag_chunks")
            client = PgVectorClient()
            try:
                client.connect()
                namespaces = ("tech_doc",)
                return {
                    "available": True,
                    "counts": {ns: client.count(table, ns) for ns in namespaces},
                }
            finally:
                client.close()
        except (VectorStoreError, OSError, ValueError) as exc:
            # 向量库属可选依赖，失败降级而非 500
            return {"available": False, "reason": str(exc)[:200]}

    @router.get("/stats")
    def stats() -> dict:
        rate_env = context.settings.env("WEB_RATE_LIMIT_PER_MINUTE", "")
        rate_limit = (
            int(rate_env)
            if rate_env.strip().lstrip("-").isdigit()
            else int(context.config.get("web.rate_limit_per_minute", 120))
        )
        kinds = store.kind_counts(WORKSPACE_KINDS)
        stages = journal.list()
        try:
            llm_configured = bool(search.connection.public(search.connection.load())["configured"])
        except StorageError:
            llm_configured = False
        return {
            "storage": "PostgreSQL",
            "kinds": kinds,
            "stages_count": len(stages),
            "latest_stage": stages[0]["title"] if stages else None,
            "llm_configured": llm_configured,
            "auth_enabled": bool(context.settings.env("WORKSPACE_ACCESS_TOKEN", "")),
            "rate_limit_per_minute": rate_limit,
            "vector": vector_stats(),
        }

    return router
