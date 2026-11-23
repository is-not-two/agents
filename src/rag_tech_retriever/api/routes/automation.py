"""自动化路由：配置 CRUD、执行、运行详情和人工确认；执行规则在编排层。"""

from pathlib import Path
from typing import Literal

import anyio
from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictBool, StrictInt

from rag_tech_retriever.agent.graph_runner import GraphWorkflowService
from rag_tech_retriever.agent.workflow_service import WorkflowService
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput, RecordOut
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.loop_service import LoopService, build_loop_service
from rag_tech_retriever.platform.record_store import RecordMissing
from rag_tech_retriever.platform.team_service import TeamService
from rag_tech_retriever.platform.workflow_composer import CONFIRMATION, WorkflowComposer


class RunInput(BaseModel):
    """实际看到的流程版本和流程输入。"""

    version: int = Field(ge=1)
    input: dict


class ConfirmInput(BaseModel):
    """人工确认：入库选片段，或图工作流/Agent 子运行的批准。"""

    version: int = Field(ge=1)
    selected: list[StrictInt] = Field(default_factory=list, max_length=500)
    approve: StrictBool | None = None


class LoopInput(BaseModel):
    """一次自动编码：仓库根目录名、目标、门禁命令、执行器与预算档位。"""

    root: str = Field(min_length=1, max_length=64)
    task: str = Field(min_length=2, max_length=2000)
    gate: str = Field(min_length=2, max_length=1000)
    engine: Literal["opencode", "aider", "model"] = "opencode"
    tier: Literal["patch", "feature", "epic"] = "patch"


class ComposeInput(BaseModel):
    """AI 自动编排：目标、模式与逐次确认（用户点击生成即确认）。"""

    goal: str = Field(min_length=1, max_length=1000)
    mode: str = "rules"
    template: str = "generic"
    confirmation: str = ""


class DraftInput(BaseModel):
    """只生成草稿：不落库，便于先改后存。"""

    goal: str = Field(min_length=1, max_length=1000)
    mode: str = "rules"
    template: str = "generic"


class ReviseInput(BaseModel):
    """带意见修订草稿：服务端重新校验并给出结构差异。"""

    draft: dict
    feedback: str = Field(min_length=1, max_length=2000)


class DraftPayload(BaseModel):
    """客户端回传待保存的草稿；服务端一律重新校验。"""

    draft: dict


class TeamRunInput(BaseModel):
    """团队协作运行：已有 Agent 名单 + 一句话目标。"""

    agent_ids: list[str] = Field(min_length=1, max_length=4)
    task: str = Field(min_length=1, max_length=2000)
    mode: str = "group_chat"
    max_rounds: StrictInt = Field(default=6, ge=1, le=12)
    approved: StrictBool = False


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

    @router.post("/api/automation/compose", status_code=201)
    def compose(payload: ComposeInput) -> dict:
        """生成 Agent 与 DAG 并落库；执行仍复用既有 workflows/{id}/run 端点。"""
        if payload.confirmation != CONFIRMATION:
            raise DomainError("请明确确认生成并运行工作流")
        composer = _composer()
        return composer.save(composer.build_draft(payload.goal, payload.mode,
                                                  template=payload.template))

    def _composer() -> WorkflowComposer:
        return WorkflowComposer(store, context.capabilities,
                                getattr(context.search, "connection", None))

    def _loop_service() -> LoopService:
        # 服务的可写路径被 systemd 限制在 data/local、output 等目录内，
        # 所以 opencode 的 HOME 必须落在 data/local 下（放 /tmp 会被 PrivateTmp 藏起来）。
        # 装配细节统一在 build_loop_service，worker 走同一份，避免两边行为不一致。
        return build_loop_service(store, getattr(context.search, "connection", None),
                                  getattr(context, "exports", None))

    @router.post("/api/automation/loop/run", status_code=201)
    def loop_run(payload: LoopInput) -> dict:
        """跑一次自动编码循环：外部只给目标与门禁，绿点与回退在服务层做。"""
        getter = getattr(context.capabilities, "code", None)
        if getter is None:
            raise DomainError("代码工作区未启用")
        target = getter.path_for(payload.root)
        return _loop_service().run(Path(target["path"]), payload.task, payload.gate,
                                   payload.engine, payload.tier, target["writable"])

    @router.get("/api/automation/code-roots")
    def code_roots() -> list:
        """管理员登记过的代码工作区；只返回名称与写权限，不含绝对路径。"""
        getter = getattr(context.capabilities, "code_roots", None)
        return getter() if callable(getter) else []

    @router.post("/api/automation/compose/draft", status_code=201)
    def compose_draft(payload: DraftInput) -> dict:
        """只生成草稿不落库：先改、再看差异、最后才保存。"""
        return _composer().build_draft(payload.goal, payload.mode, template=payload.template)

    @router.post("/api/automation/compose/revise")
    def compose_revise(payload: ReviseInput) -> dict:
        """按意见重出草稿，返回新草稿与结构差异；不写库。"""
        return _composer().revise(payload.draft, payload.feedback)

    @router.post("/api/automation/compose/save", status_code=201)
    def compose_save(payload: DraftPayload) -> dict:
        """确认后的草稿才落库；草稿里的权限字段会重新校验，不信任前端。"""
        return _composer().save(payload.draft)

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

    @router.post("/api/automation/teams/run", status_code=201)
    async def team_run(payload: TeamRunInput) -> dict:
        """让已有 Agent 组成团队跑一轮：群聊轮流发言，或磁石模式自动规划。

        写操作不在本轮执行：未批准时把「需批准」如实回给模型，由用户带 approved 重跑。
        """
        service_team = TeamService(store, context.capabilities,
                                   getattr(context.runtime, "connection", None))
        return await service_team.run(payload.agent_ids, payload.task, payload.mode,
                                      payload.max_rounds, payload.approved)

    @router.get("/api/workflow-runs")
    def runs() -> list:
        # 列表不带大正文与冻结配置，详情按需读取；最近 100 次不删除历史。
        heavy = ("result", "workflow", "agent", "steps", "node_outputs", "agent_snapshots", "turns")
        rows = [row for kind in ("workflow_run", "agent_session") for row in
                store.list(kind, limit=100, data_kinds=("answer", "ingest", "graph", "team", "loop"),
                           omit=heavy + (("input",) if kind == "workflow_run" else ()))]
        for row in rows:
            data = row["data"]
            legacy_input = data.pop("input", None)
            if data.get("private_interview") and not data.get("interview_lead_id") and isinstance(legacy_input, dict):
                lead_id = legacy_input.get("lead_id")
                if isinstance(lead_id, str) and len(lead_id) <= 100:
                    data["interview_lead_id"] = lead_id
        return sorted(rows, key=lambda row: row["data"].get("started_at", ""), reverse=True)[:100]

    @router.get("/api/workflow-runs/{record_id}")
    def run_detail(record_id: str) -> dict:
        row = store.get(record_id)
        if row["kind"] not in {"workflow_run", "agent_session"} or row["data"].get("kind") not in {"answer", "ingest", "graph", "team", "loop"}:
            raise RecordMissing("运行记录不存在")
        return row

    @router.post("/api/workflow-runs/{record_id}/resume", response_model=RecordOut)
    async def resume(record_id: str, payload: ConfirmInput) -> dict:
        row = store.get(record_id)
        if row["data"].get("kind") != "graph":
            raise DomainError("只有图工作流支持崩溃恢复")
        return await graph.resume(record_id, payload.version)

    @router.post("/api/workflow-runs/{record_id}/confirm")
    async def confirm(record_id: str, payload: ConfirmInput) -> dict:
        row = store.get(record_id)
        if row["data"].get("kind") == "team":
            raise DomainError("团队运行不支持确认：写操作请在重新运行时带 approved")
        if row["data"].get("kind") == "graph":
            if payload.approve is None:
                raise DomainError("图工作流确认必须明确 approve")
            return await graph.confirm(record_id, payload.version, payload.approve)
        if not payload.selected:
            raise DomainError("入库确认必须选择片段")
        return await anyio.to_thread.run_sync(service.confirm, record_id, payload.version, payload.selected)

    return router
