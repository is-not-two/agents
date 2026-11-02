"""Explicit collaboration plan/child confirmations; authenticated by the main app."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.domains.life_planning import DomainError


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=100)
    version: StrictInt = Field(ge=1)
    query: str = Field(min_length=1, max_length=4000)
    plan: list[dict] | None = Field(default=None, max_length=32)
    confirmation: str


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    approve: StrictBool
    confirmation: str


class ChildDecisionInput(DecisionInput):
    child_version: StrictInt = Field(ge=1)


class ExecuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    confirmation: str


def create_router(context: WorkspaceContext) -> APIRouter:
    """Only saved Profile grants may dispatch workers; no browser-provided tool code."""
    router = APIRouter(prefix="/api/collaborations")
    service = context.collaboration

    @router.get("/status")
    def status() -> dict:
        return {**service.config, "quality_verified": False, "production_rollout": False,
                "execution": "sequential_worker_as_tool", "automatic_retry": False}

    @router.get("")
    def runs() -> list:
        return service.list()

    @router.get("/{run_id}")
    def get(run_id: str) -> dict:
        row = service.get(run_id)
        child = row["data"]["shared_state"].get("pending_child")
        return {**row, "pending_child_run": context.store.get(child) if child else None}

    @router.post("", status_code=201)
    async def start(payload: PlanInput) -> dict:
        required = "仅创建人工计划" if payload.plan is not None else "生成协作计划（可能计费）"
        if payload.confirmation != required:
            raise DomainError("请明确选择无模型人工计划或可能计费的模型计划")
        return await service.start(payload.agent_id, payload.version, payload.query, payload.plan)

    @router.post("/{run_id}/confirm")
    async def confirm(run_id: str, payload: DecisionInput) -> dict:
        required = "批准计划，不批准Worker写操作" if payload.approve else "拒绝计划"
        if payload.confirmation != required:
            raise DomainError("计划批准不能替代Worker写操作批准")
        return await service.confirm(run_id, payload.version, payload.approve)

    @router.post("/{run_id}/execute")
    async def execute(run_id: str, payload: ExecuteInput) -> dict:
        if payload.confirmation != "执行协作计划（可能计费）":
            raise DomainError("执行前须明确确认可能计费的Worker调用")
        return await service.execute(run_id, payload.version)

    @router.post("/{run_id}/child-confirm")
    async def child_confirm(run_id: str, payload: ChildDecisionInput) -> dict:
        required = "批准当前Worker操作" if payload.approve else "拒绝当前Worker操作"
        if payload.confirmation != required:
            raise DomainError("必须单独审阅当前Worker的工具与参数")
        return await service.confirm_child(run_id, payload.version, payload.child_version, payload.approve)

    @router.post("/{run_id}/abort")
    def abort(run_id: str, payload: ExecuteInput) -> dict:
        return service.abort(run_id, payload.version, payload.confirmation)

    return router
