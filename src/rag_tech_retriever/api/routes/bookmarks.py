"""bookmarks 路由：网页收藏的列表、创建与更新（删除/恢复走通用 records）。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput, RecordOut
from rag_tech_retriever.domains.bookmarks import validate_bookmark


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/bookmarks", response_model=list[RecordOut])
    def bookmark_list(trash: bool = False) -> list:
        return store.list("bookmark", deleted=trash)

    @router.post("/api/bookmarks", status_code=201, response_model=RecordOut)
    def bookmark_create(payload: RecordInput) -> dict:
        return store.save("bookmark", validate_bookmark(payload.data))

    @router.put("/api/bookmarks/{record_id}", response_model=RecordOut)
    def bookmark_update(record_id: str, payload: RecordInput) -> dict:
        return store.save("bookmark", validate_bookmark(payload.data), record_id, payload.version)

    return router
