"""任务队列接口：入队、查状态、取消、死信重放与概览。

同步执行的端点保留不动；这里提供的是异步排队入口，
让分钟级的模型调用与编码循环不再挂在一次 HTTP 请求上。
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.queue_service import QueueService
from rag_tech_retriever.platform.task_queue_store import TaskQueueStore


class EnqueueInput(BaseModel):
    """入队参数：任务类型、载荷、重试上限与优先级。"""

    kind: Literal["team", "loop"]
    payload: dict
    max_attempts: StrictInt = Field(default=3, ge=1, le=10)
    priority: StrictInt = Field(default=50, ge=0, le=100)
    idempotency_key: str = Field(default="", max_length=200)


def create_router(context: WorkspaceContext) -> APIRouter:
    """注入存储层；队列表不存在时给出明确提示而不是 500。"""
    router = APIRouter()

    def service() -> QueueService:
        queue = TaskQueueStore(context.store)
        if not queue.table_exists():
            raise DomainError("任务队列尚未初始化，请先由管理员执行队列表迁移")
        return QueueService(queue)

    @router.post("/api/automation/queue", status_code=201)
    def enqueue(payload: EnqueueInput) -> dict:
        """入队一个任务，返回任务视图；同一幂等键重复提交只会有一个任务。"""
        key = payload.idempotency_key.strip() or None
        return service().enqueue(payload.kind, payload.payload,
                                 max_attempts=payload.max_attempts,
                                 priority=payload.priority, idempotency_key=key)

    @router.get("/api/automation/queue/stats")
    def stats() -> dict:
        """各状态任务计数。"""
        return service().stats()

    @router.get("/api/automation/queue")
    def list_jobs(status: str = "", limit: int = 50) -> list:
        """任务列表；传 status 可只看某一状态（如 dead 看死信）。"""
        return service().list_jobs(status=status.strip() or None, limit=max(1, min(limit, 200)))

    @router.get("/api/automation/queue/{job_id}")
    def job_detail(job_id: str) -> dict:
        """任务详情：含载荷、结果与检查点。"""
        return service().detail(job_id)

    @router.post("/api/automation/queue/{job_id}/cancel")
    def cancel(job_id: str) -> dict:
        """取消排队中或执行中的任务。"""
        return service().cancel(job_id)

    @router.post("/api/automation/queue/{job_id}/replay")
    def replay(job_id: str) -> dict:
        """死信重放：回到队列并重置尝试计数。"""
        return service().replay(job_id)

    return router
