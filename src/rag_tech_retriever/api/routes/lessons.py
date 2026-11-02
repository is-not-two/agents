"""lessons 路由：谨记名单的增改查（软删除与恢复复用通用 records/history 接口）。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.lessons import validate_lesson


def create_router(context: WorkspaceContext) -> APIRouter:
    """谨记名单：list/create/update；删除走 /api/records/{id}，恢复走 /api/records/{id}/restore。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/lessons")
    def lessons_list(trash: bool = False) -> list:
        return store.list("lesson", deleted=trash)

    @router.post("/api/lessons", status_code=201)
    def lessons_create(payload: RecordInput) -> dict:
        return store.save("lesson", validate_lesson(payload.data))

    @router.put("/api/lessons/{record_id}")
    def lessons_update(record_id: str, payload: RecordInput) -> dict:
        return store.save("lesson", validate_lesson(payload.data), record_id, payload.version)

    return router
