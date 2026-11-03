"""search 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter, HTTPException

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import QueryInput, QueryOut


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    search = context.search

    @router.get("/api/query/options")
    def options() -> dict:
        return search.catalog.options()

    @router.post("/api/query", response_model=QueryOut)
    def query(payload: QueryInput) -> dict:
        if payload.scope not in {"all", "personal", "docs", "planning"} or payload.mode not in {
            "text",
            "vector",
        }:
            raise HTTPException(400, "查询范围或模式不支持")
        if not payload.query.strip():
            raise HTTPException(400, "请输入查询内容")
        if payload.namespace is None:
            return search.query(payload.query.strip(), payload.scope, payload.mode, payload.generate)
        return search.query(payload.query.strip(), payload.scope, payload.mode, payload.generate, payload.namespace)

    return router
