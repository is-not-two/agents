"""knowledge 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.knowledge import validate_knowledge


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/knowledge")
    def knowledge_list(trash: bool = False) -> list:
        return store.list("knowledge", deleted=trash)

    @router.post("/api/knowledge", status_code=201)
    def knowledge_create(payload: RecordInput) -> dict:
        return store.save("knowledge", validate_knowledge(payload.data))

    @router.put("/api/knowledge/{record_id}")
    def knowledge_update(record_id: str, payload: RecordInput) -> dict:
        return store.save("knowledge", validate_knowledge(payload.data), record_id, payload.version)

    return router
