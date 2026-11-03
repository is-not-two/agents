"""Skills/MCP discovery and versioned Agent execution APIs, protected by workspace auth."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from rag_tech_retriever.agent.memory import AgentMemory
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.agent_capabilities import BUILTINS
from rag_tech_retriever.platform.mcp_client import ToolError


class SkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=65536)
    revision: str | None = None


class AgentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    query: str = Field(min_length=1, max_length=4000)


class ToolCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)


class MemoryProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_version: StrictInt = Field(ge=1)
    content: str = Field(min_length=1, max_length=1000000)
    request_id: str = Field(min_length=1, max_length=100)


class MemoryDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_version: StrictInt = Field(ge=1)
    version: StrictInt = Field(ge=1)
    action: str
    confirmation: str


class ContinueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    query: str = Field(min_length=1, max_length=4000)


class CloseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    approve: StrictBool


class GitHubPreviewInput(BaseModel):
    """Only a repository URL and optional branch/tag, never shell parameters."""
    model_config = ConfigDict(extra="forbid")
    repo_url: str = Field(min_length=1, max_length=2048)
    ref: str | None = Field(default=None, max_length=100)


class GitHubImportInput(BaseModel):
    """Explicit selection of an immutable preview; no automatic script execution."""
    model_config = ConfigDict(extra="forbid")
    import_id: str = Field(min_length=32, max_length=32)
    selected: list[str] = Field(min_length=1, max_length=32)
    confirm: StrictBool


def create_router(context: WorkspaceContext) -> APIRouter:
    """Configuration grants come from the saved Agent, never from run request bodies."""
    router = APIRouter()
    caps, runtime = context.capabilities, context.runtime
    memory = AgentMemory(context.store, caps.limits)

    @router.get("/api/capabilities")
    def capabilities() -> dict:
        return {"skills": True, "mcp_client": True, "agent_runtime": True,
                "model_tool_calling": "not_verified", "script_execution": False,
                "web_search": caps.web.public(), "http_tools": caps.http.public(),
                "limits": caps.limits, "builtin_tools": [{"name": key, **value} for key, value in BUILTINS.items()]}

    @router.get("/api/capabilities/tools")
    async def tool_catalog() -> dict:
        """统一目录：内置工具 + 管理员 HTTP 工具 + 已启用 MCP 服务（不触发写入）。"""
        mcp, errors = [], []
        for server in caps.mcp.public():
            if not (server["enabled"] and server["trusted"]):
                continue
            try:
                for spec in await caps.mcp.discover(server["id"]):
                    mcp.append({**spec, "source": "mcp", "server_id": server["id"]})
            except (ToolError, DomainError) as exc:
                errors.append({"server_id": server["id"], "error": str(exc)})
        return {"builtin": [{"name": key, **value, "source": "builtin"} for key, value in BUILTINS.items()],
                "http": [{**item, "source": "http"} for item in caps.http.public()],
                "mcp": mcp, "mcp_errors": errors}

    @router.get("/api/agents/{record_id}/memory")
    def memory_list(record_id: str) -> list:
        return memory.list(record_id)

    @router.post("/api/agents/{record_id}/memory", status_code=201)
    def memory_propose(record_id: str, payload: MemoryProposalInput) -> dict:
        return memory.propose(record_id, payload.agent_version, payload.content, payload.request_id)

    @router.post("/api/agents/{record_id}/memory/{memory_id}/decide")
    def memory_decide(record_id: str, memory_id: str, payload: MemoryDecisionInput) -> dict:
        return memory.decide(record_id, memory_id, payload.version, payload.agent_version,
                             payload.action, payload.confirmation)

    @router.get("/api/skills")
    def skills() -> list:
        return caps.skills.list()

    @router.get("/api/skills/{name}")
    def skill(name: str) -> dict:
        return caps.skills.get(name)

    @router.put("/api/skills/{name}")
    def save_skill(name: str, payload: SkillInput) -> dict:
        return caps.skills.save(name, payload.content, payload.revision)

    @router.post("/api/skills/github/preview")
    def github_preview(payload: GitHubPreviewInput) -> dict:
        return caps.github.preview(payload.repo_url, payload.ref)

    @router.post("/api/skills/github/import")
    def github_import(payload: GitHubImportInput) -> dict:
        if not payload.confirm:
            from rag_tech_retriever.domains.life_planning import DomainError

            raise DomainError("请先审阅第三方技能内容并明确确认")
        return caps.github.apply(payload.import_id, payload.selected)

    @router.get("/api/mcp/servers")
    def mcp_servers() -> list:
        return caps.mcp.public()

    @router.post("/api/mcp/servers/{server_id}/test")
    async def mcp_test(server_id: str) -> dict:
        tools = await caps.mcp.discover(server_id)
        return {"status": "connected", "tools": tools}

    @router.get("/api/agents/{record_id}/tools")
    async def tools(record_id: str) -> list:
        agent = runtime.agent(record_id)
        specs, _ = await caps.catalog(agent["data"])
        return list(specs.values())

    @router.post("/api/agents/{record_id}/run")
    async def run(record_id: str, payload: AgentRunInput) -> dict:
        return await runtime.start(record_id, payload.version, payload.query)

    @router.post("/api/agents/{record_id}/tools/call")
    async def call(record_id: str, payload: ToolCallInput) -> dict:
        return await runtime.start(record_id, payload.version, "手动调用工具", payload.model_dump())

    @router.get("/api/agent-runs/{record_id}")
    def run_detail(record_id: str) -> dict:
        return runtime.run_record(record_id)

    @router.get("/api/agent-runs")
    def runs() -> list:
        omit = ("input", "result", "workflow", "agent", "steps", "messages", "skills", "tool_specs", "pending_calls")
        rows = [row for kind in ("workflow_run", "agent_session") for row in
                context.store.list(kind, limit=100, data_kinds=("agent",), omit=omit)]
        return sorted(rows, key=lambda row: row["data"].get("started_at", ""), reverse=True)[:100]

    @router.post("/api/agent-runs/{record_id}/continue")
    async def continue_run(record_id: str, payload: ContinueInput) -> dict:
        return await runtime.continue_run(record_id, payload.version, payload.query)

    @router.post("/api/agent-runs/{record_id}/close")
    def close_run(record_id: str, payload: CloseInput) -> dict:
        return runtime.close_run(record_id, payload.version)

    @router.post("/api/agent-runs/{record_id}/confirm")
    async def confirm(record_id: str, payload: ApprovalInput) -> dict:
        return await runtime.confirm(record_id, payload.version, payload.approve)

    return router
