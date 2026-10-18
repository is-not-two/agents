"""history 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext, visible
from rag_tech_retriever.api.models import RestoreInput


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.delete("/api/records/{record_id}")
    def record_delete(record_id: str, version: int) -> dict:
        return store.delete(record_id, version)

    @router.get("/api/records/{record_id}/history")
    def record_history(record_id: str) -> list:
        store.get(record_id, True)
        return store.history(record_id)

    @router.post("/api/records/{record_id}/restore")
    def record_restore(record_id: str, payload: RestoreInput) -> dict:
        return visible(store.restore(record_id, payload.target_version, payload.current_version))

    return router
