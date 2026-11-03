"""自动化路由：配置 CRUD、执行、运行详情和人工确认；执行规则在编排层。"""

import anyio
from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictBool, StrictInt

from rag_tech_retriever.agent.graph_runner import GraphWorkflowService
from rag_tech_retriever.agent.workflow_service import WorkflowService
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing


class RunInput(BaseModel):
    """实际看到的流程版本和流程输入。"""

    version: int = Field(ge=1)
    input: dict


class ConfirmInput(BaseModel):
    """人工确认：入库选片段，或图工作流/Agent 子运行的批准。"""

    version: int = Field(ge=1)
    selected: list[StrictInt] = Field(default_factory=list, max_length=500)
    approve: StrictBool | None = None


def create_router(context: WorkspaceContext) -> APIRouter:
    """注入现有持久化与检索服务，统一受主应用鉴权保护。"""
    router = APIRouter()
    store = context.store
    service = WorkflowService(store, context.search, context.capabilities)
    graph = GraphWorkflowService(store, context.search, context.capabilities, context.runtime)

    def checked(data: dict) -> dict:
        return graph.check(data) if data.get("kind") == "graph" else service.check_workflow(data)

    @router.post("/api/automation/setup")
    def setup() -> dict:
        return service.setup()

    @router.get("/api/agents")
    def agents() -> list:
        # Normalize old records on read without rewriting their stored version.
        return [{**row, "data": validate_agent(row["data"])} for row in store.list("agent_profile")]

    @router.post("/api/agents", status_code=201)
    def agent_create(payload: RecordInput) -> dict:
        data = context.capabilities.validate_binding(validate_agent(payload.data))
        return store.save("agent_profile", data)

    @router.put("/api/agents/{record_id}")
    def agent_update(record_id: str, payload: RecordInput) -> dict:
        current = service.agent(record_id)
        # Old UI forms do not know capability fields; preserve omitted grants.
        data = context.capabilities.validate_binding(validate_agent({**current["data"], **payload.data}))
        return store.save("agent_profile", data, record_id, payload.version)

    @router.get("/api/workflows")
    def workflows() -> list:
        return store.list("workflow")

    @router.post("/api/workflows", status_code=201)
    def workflow_create(payload: RecordInput) -> dict:
        return store.save("workflow", checked(payload.data))

    @router.put("/api/workflows/{record_id}")
    def workflow_update(record_id: str, payload: RecordInput) -> dict:
        if store.get(record_id)["kind"] != "workflow":
            raise RecordMissing("流程不存在")
        return store.save("workflow", checked(payload.data), record_id, payload.version)

    @router.post("/api/workflows/{record_id}/run")
    async def workflow_run(record_id: str, payload: RunInput) -> dict:
        current = store.get(record_id)
        if current["kind"] != "workflow":
            raise RecordMissing("流程不存在")
        if current["data"].get("kind") == "graph":
            return await graph.run(record_id, payload.version, payload.input)
        return await anyio.to_thread.run_sync(service.run, record_id, payload.version, payload.input)

    @router.get("/api/workflow-runs")
    def runs() -> list:
        # 列表不带大正文与冻结配置，详情按需读取；最近 100 次不删除历史。
        rows = [row for kind in ("workflow_run", "agent_session") for row in
                store.list(kind, limit=100, data_kinds=("answer", "ingest", "graph"),
                           omit=("input", "result", "workflow", "agent", "steps", "node_outputs", "agent_snapshots"))]
        return sorted(rows, key=lambda row: row["data"].get("started_at", ""), reverse=True)[:100]

    @router.get("/api/workflow-runs/{record_id}")
    def run_detail(record_id: str) -> dict:
        row = store.get(record_id)
        if row["kind"] not in {"workflow_run", "agent_session"} or row["data"].get("kind") not in {"answer", "ingest", "graph"}:
            raise RecordMissing("运行记录不存在")
        return row

    @router.post("/api/workflow-runs/{record_id}/confirm")
    async def confirm(record_id: str, payload: ConfirmInput) -> dict:
        row = store.get(record_id)
        if row["data"].get("kind") == "graph":
            if payload.approve is None:
                raise DomainError("图工作流确认必须明确 approve")
            return await graph.confirm(record_id, payload.version, payload.approve)
        if not payload.selected:
            raise DomainError("入库确认必须选择片段")
        return await anyio.to_thread.run_sync(service.confirm, record_id, payload.version, payload.selected)

    return router
