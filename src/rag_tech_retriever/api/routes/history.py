"""history 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext, visible
from rag_tech_retriever.api.models import RestoreInput
from rag_tech_retriever.domains.jobs import VALIDATORS as JOB_KINDS
from rag_tech_retriever.platform.jobs import JobsService
from rag_tech_retriever.platform.record_store import VersionConflict


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.delete("/api/records/{record_id}")
    def record_delete(record_id: str, version: int) -> dict:
        kind = store.get(record_id)["kind"]
        if kind in {"notification_outbox", "learning_review", "agent_memory", "agent_session"}:
            raise VersionConflict("此类私有运行或审计记录须通过专用入口处理，不能通用删除")
        if kind in JOB_KINDS:
            return JobsService(store).archive(record_id, version)
        return store.delete(record_id, version)

    @router.get("/api/records/{record_id}/history")
    def record_history(record_id: str) -> list:
        store.get(record_id, True)
        return store.history(record_id)

    @router.post("/api/records/{record_id}/restore")
    def record_restore(record_id: str, payload: RestoreInput) -> dict:
        kind = store.get(record_id, True)["kind"]
        if kind in {"notification_outbox", "learning_review", "agent_memory", "agent_session"}:
            raise VersionConflict("此类私有运行或审计记录不能通过通用历史恢复重放")
        if kind in JOB_KINDS:
            return JobsService(store).restore(record_id, payload.target_version, payload.current_version)
        return visible(store.restore(record_id, payload.target_version, payload.current_version))

    return router
