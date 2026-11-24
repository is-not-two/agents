"""self_traits 路由：人物特质卡的增改查（软删除与恢复复用通用 records 接口）。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput, RecordOut
from rag_tech_retriever.domains.self_traits import validate_self_trait


def create_router(context: WorkspaceContext) -> APIRouter:
    """人物：list/create/update；修改历史走 /api/records/{id}/history。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/traits", response_model=list[RecordOut])
    def trait_list(trash: bool = False) -> list:
        return store.list("self_trait", deleted=trash)

    @router.post("/api/traits", status_code=201, response_model=RecordOut)
    def trait_create(payload: RecordInput) -> dict:
        return store.save("self_trait", validate_self_trait(payload.data))

    @router.put("/api/traits/{record_id}", response_model=RecordOut)
    def trait_update(record_id: str, payload: RecordInput) -> dict:
        return store.save(
            "self_trait", validate_self_trait(payload.data), record_id, payload.version
        )

    return router
