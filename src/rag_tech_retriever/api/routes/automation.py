"""自动化路由：配置 CRUD、执行、运行详情和人工确认；执行规则在编排层。"""

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from rag_tech_retriever.agent.workflow_service import WorkflowService
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.platform.record_store import RecordMissing


class RunInput(BaseModel):
    """实际看到的流程版本和流程输入。"""

    version: int = Field(ge=1)
    input: dict


class ConfirmInput(BaseModel):
    """人工选中的片段索引及预览版本。"""

    version: int = Field(ge=1)
    selected: list[StrictInt] = Field(min_length=1, max_length=500)


def create_router(context: WorkspaceContext) -> APIRouter:
    """注入现有持久化与检索服务，统一受主应用鉴权保护。"""
    router = APIRouter()
    store = context.store
    service = WorkflowService(store, context.search)

    @router.post("/api/automation/setup")
    def setup() -> dict:
        return service.setup()

    @router.get("/api/agents")
    def agents() -> list:
        return store.list("agent_profile")

    @router.post("/api/agents", status_code=201)
    def agent_create(payload: RecordInput) -> dict:
        return store.save("agent_profile", validate_agent(payload.data))

    @router.put("/api/agents/{record_id}")
    def agent_update(record_id: str, payload: RecordInput) -> dict:
        service.agent(record_id)
        return store.save("agent_profile", validate_agent(payload.data), record_id, payload.version)

    @router.get("/api/workflows")
    def workflows() -> list:
        return store.list("workflow")

    @router.post("/api/workflows", status_code=201)
    def workflow_create(payload: RecordInput) -> dict:
        return store.save("workflow", service.check_workflow(payload.data))

    @router.put("/api/workflows/{record_id}")
    def workflow_update(record_id: str, payload: RecordInput) -> dict:
        if store.get(record_id)["kind"] != "workflow":
            raise RecordMissing("流程不存在")
        return store.save("workflow", service.check_workflow(payload.data), record_id, payload.version)

    @router.post("/api/workflows/{record_id}/run")
    def workflow_run(record_id: str, payload: RunInput) -> dict:
        return service.run(record_id, payload.version, payload.input)

    @router.get("/api/workflow-runs")
    def runs() -> list:
        # 列表不带大正文与冻结配置，详情按需读取；最近 100 次不删除历史。
        return store.list("workflow_run", limit=100, omit=("input", "result", "workflow", "agent", "steps"))

    @router.get("/api/workflow-runs/{record_id}")
    def run_detail(record_id: str) -> dict:
        row = store.get(record_id)
        if row["kind"] != "workflow_run":
            raise RecordMissing("运行记录不存在")
        return row

    @router.post("/api/workflow-runs/{record_id}/confirm")
    def confirm(record_id: str, payload: ConfirmInput) -> dict:
        return service.confirm(record_id, payload.version, payload.selected)

    return router
