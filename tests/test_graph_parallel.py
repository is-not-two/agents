"""DAG 并行调度：同波次并发、并行度上限、节点级失败/超时隔离、并发待确认。"""

import asyncio
import time
from copy import deepcopy

import pytest

from rag_tech_retriever.agent.graph_runner import GraphWorkflowService, _Pause
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.record_store import VersionConflict


class FakeStore:
    """内存版运行记录存储，按版本号模拟乐观锁。"""

    def __init__(self, data: dict) -> None:
        self.row = {"id": "run", "kind": "workflow_run", "version": 1, "data": deepcopy(data)}

    def save(self, kind: str, data: dict, record_id: str | None = None, version: int | None = None) -> dict:
        if record_id is None:
            self.row = {"id": "run", "kind": kind, "version": 1, "data": deepcopy(data)}
            return deepcopy(self.row)
        if version != self.row["version"]:
            raise VersionConflict("版本冲突")
        self.row = {"id": record_id, "kind": kind, "version": self.row["version"] + 1,
                    "data": deepcopy(data)}
        return deepcopy(self.row)

    def get(self, record_id: str) -> dict:
        return deepcopy(self.row)


class FakeRuntime:
    """只实现图工作流用到的 confirm，记录调用顺序。"""

    def __init__(self) -> None:
        self.calls = []

    async def confirm(self, run_id: str, version: int, approve: bool) -> dict:
        self.calls.append((run_id, version, approve))
        status = "completed" if approve else "failed"
        return {"version": 1, "data": {"status": status,
                                       "result": {"answer": run_id, "notes": []}}}


def branch_graph(max_parallel: int = 2, timeout: int = 30) -> dict:
    return {
        "title": "并行分支", "kind": "graph",
        "nodes": [{"id": "input", "type": "input"},
                  {"id": "a", "type": "merge"}, {"id": "b", "type": "merge"}],
        "edges": [["input", "a"], ["input", "b"]],
        "max_parallel": max_parallel, "max_retries": 0, "node_timeout_seconds": timeout,
    }


def agent_graph() -> dict:
    return {
        "title": "并行 Agent", "kind": "graph",
        "nodes": [{"id": "input", "type": "input"},
                  {"id": "a", "type": "agent", "agent_id": "agent-a", "query": "{{input.query}}"},
                  {"id": "b", "type": "agent", "agent_id": "agent-b", "query": "{{input.query}}"}],
        "edges": [["input", "a"], ["input", "b"]],
        "max_parallel": 2, "max_retries": 0, "node_timeout_seconds": 30,
    }


def run_record(cfg: dict, snapshots: dict | None = None) -> dict:
    return {
        "title": cfg["title"], "workflow_id": "wf", "kind": "graph", "status": "running",
        "started_at": "", "input": {"query": "检索"},
        "workflow": {"id": "wf", "kind": "workflow", "version": 1, "data": cfg},
        "agent_snapshots": snapshots or {},
        "steps": [], "node_outputs": {}, "node_status": {}, "pending_node": "",
        "pending_kind": "", "pending_child": None, "pending_children": [],
        "approved_nodes": [], "result": {"answer": "", "notes": []},
    }


def service_with(cfg: dict, execute, snapshots: dict | None = None) -> tuple[GraphWorkflowService, FakeStore]:
    store = FakeStore(run_record(cfg, snapshots))
    service = GraphWorkflowService(store, None, None, FakeRuntime())
    service._execute_node = execute
    return service, store


def test_independent_branches_run_in_the_same_wave():
    cfg = branch_graph()
    spans: dict[str, list[float]] = {}

    async def execute(data, node):
        spans.setdefault(node["id"], []).append(time.monotonic())
        await asyncio.sleep(0.05)
        spans[node["id"]].append(time.monotonic())
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    assert result["data"]["status"] == "completed"
    # a、b 的执行区间必须重叠，否则仍是串行推进。
    assert spans["a"][0] < spans["b"][1] and spans["b"][0] < spans["a"][1]


def test_max_parallel_one_keeps_execution_serial():
    cfg = branch_graph(max_parallel=1)
    active, peak = 0, 0

    async def execute(data, node):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    assert result["data"]["status"] == "completed"
    assert peak == 1


@pytest.mark.parametrize("error", [DomainError, ToolError])
def test_one_failure_does_not_cancel_sibling(error):
    cfg = branch_graph()

    async def execute(data, node):
        if node["id"] == "a":
            raise error("a 失败")
        await asyncio.sleep(0.02)
        return {"answer": "b 完成"}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["status"] == "failed"
    assert data["node_status"]["b"] == "completed"
    assert data["node_status"]["a"] == "failed"
    assert "a 失败" in data["result"]["notes"]


def test_node_timeout_is_isolated():
    cfg = branch_graph(timeout=0.05)

    async def execute(data, node):
        if node["id"] == "a":
            await asyncio.sleep(0.2)
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["node_status"]["a"] == "failed"
    assert data["node_status"]["b"] == "completed"
    assert any("超时" in note for note in data["result"]["notes"])


def test_resume_requeues_stuck_readonly_node():
    cfg = branch_graph(max_parallel=1)
    cfg["nodes"][1]["type"] = "retrieve"
    cfg["nodes"][1]["agent_id"] = "a"
    cfg["nodes"][2]["type"] = "retrieve"
    cfg["nodes"][2]["agent_id"] = "a"
    store = FakeStore(run_record(cfg))
    store.row["data"]["node_status"] = {"input": "completed", "a": "running"}
    store.row["data"]["node_outputs"] = {"input": {}}

    async def execute(data, node):
        return {"answer": node["id"]}

    service = GraphWorkflowService(store, None, None, FakeRuntime())
    service._execute_node = execute
    resumed = asyncio.run(service.resume("run", store.row["version"]))
    assert resumed["data"]["status"] == "completed"
    assert resumed["data"]["node_status"]["a"] == "completed"
    assert resumed["data"]["recovery"][0]["nodes"] == ["a"]


def test_resume_refuses_agent_node_side_effect():
    cfg = branch_graph(max_parallel=1)
    cfg["nodes"][1]["type"] = "agent"

    async def execute(data, node):
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    stuck = store.get("run")
    stuck["data"]["status"] = "running"
    stuck["data"]["node_status"]["a"] = "running"
    store.save("workflow_run", stuck["data"], stuck["id"], stuck["version"])
    with pytest.raises(DomainError):
        asyncio.run(service.resume("run", store.get("run")["version"]))


def test_dynamic_fill_starts_ready_node_before_slow_sibling_finishes():
    cfg = {
        "title": "动态补位",
        "kind": "graph",
        "nodes": [
            {"id": "input", "type": "input"},
            {"id": "a", "type": "merge"},
            {"id": "b", "type": "merge"},
            {"id": "c", "type": "merge"},
        ],
        "edges": [["input", "a"], ["input", "b"], ["b", "c"]],
        "max_parallel": 2,
        "max_retries": 0,
        "node_timeout_seconds": 30,
    }
    order = []

    async def execute(data, node):
        if node["id"] == "a":
            await asyncio.sleep(0.12)
        order.append(node["id"])
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    assert result["data"]["status"] == "completed"
    assert order == ["input", "b", "c", "a"]


def test_tool_error_is_retried_until_success():
    cfg = branch_graph(max_parallel=1)
    cfg["nodes"][1]["retry"] = {"max_attempts": 2, "backoff_ms": 100, "retry_on": ["tool_error"]}
    calls = []

    async def execute(data, node):
        if node["id"] == "a":
            calls.append(node["id"])
            if len(calls) == 1:
                raise ToolError("临时工具错误")
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["status"] == "completed"
    assert data["node_status"]["a"] == "completed"
    assert len(data["node_attempts"]["a"]) == 2
    assert data["node_attempts"]["a"][0]["status"] == "failed"
    assert data["node_attempts"]["a"][1]["status"] == "completed"


def test_agent_node_is_not_retried_by_default():
    cfg = branch_graph(max_parallel=1)
    cfg["max_retries"] = 3
    cfg["nodes"][1]["type"] = "agent"

    async def execute(data, node):
        if node["id"] == "a":
            raise ToolError("Agent 工具失败")
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    assert result["data"]["node_status"]["a"] == "failed"
    assert len(result["data"]["node_attempts"]["a"]) == 1


def test_domain_error_is_not_retried_by_default():
    cfg = branch_graph(max_parallel=1)
    cfg["nodes"][1]["retry"] = {"max_attempts": 3, "backoff_ms": 100}
    calls = []

    async def execute(data, node):
        if node["id"] == "a":
            calls.append(node["id"])
            raise DomainError("配置错误")
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    assert result["data"]["node_status"]["a"] == "failed"
    assert len(result["data"]["node_attempts"]["a"]) == 1


def _linear_graph(last_node: dict, join_policy: str = "all_success") -> dict:
    cfg = branch_graph(max_parallel=1)
    cfg["nodes"] = [{"id": "input", "type": "input"},
                    {"id": "a", "type": "merge", **last_node},
                    {"id": "final", "type": "merge"}]
    cfg["edges"] = [["input", "a"], ["a", "final"]]
    cfg["join_policy"] = join_policy
    return cfg


def test_on_error_continue_skips_node_and_unblocks_downstream():
    cfg = _linear_graph({"on_error": "continue"})

    async def execute(data, node):
        if node["id"] == "a":
            raise ToolError("工具不可用")
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["node_status"]["a"] == "skipped"
    assert data["node_status"]["final"] == "completed"
    assert data["status"] == "fallback"
    assert any("按失败策略跳过" in note for note in data["result"]["notes"])


def test_on_error_fallback_uses_declared_output():
    cfg = _linear_graph({"on_error": "fallback", "fallback": {"answer": "兜底结果"}})

    async def execute(data, node):
        if node["id"] == "a":
            raise ToolError("工具不可用")
        if node["id"] == "final":
            return {"answer": data["node_outputs"]["a"]["answer"]}
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["node_status"]["a"] == "fallback"
    assert data["node_status"]["final"] == "completed"
    assert "兜底结果" in data["result"]["answer"]
    assert data["status"] == "fallback"


def test_any_success_join_does_not_wait_for_failed_sibling():
    cfg = branch_graph(max_parallel=2)
    cfg["join_policy"] = "any_success"
    cfg["nodes"].append({"id": "final", "type": "merge"})
    cfg["edges"] = [["input", "a"], ["input", "b"], ["a", "final"], ["b", "final"]]

    async def execute(data, node):
        if node["id"] == "a":
            raise ToolError("a 失败")
        if node["id"] == "final":
            return {"answer": data["node_outputs"]["b"]["answer"]}
        return {"answer": node["id"]}

    service, store = service_with(cfg, execute)
    result = asyncio.run(service._drive(store.row))
    data = result["data"]
    assert data["node_status"]["a"] == "failed"
    assert data["node_status"]["b"] == "completed"
    assert data["node_status"]["final"] == "completed"
    assert data["status"] == "fallback"


def test_parallel_agents_pause_and_confirm_together():
    async def execute(data, node):
        if node["id"] == "input":
            return {"input": deepcopy(data["input"])}
        raise _Pause("agent", node["id"], {"run_id": node["id"] + "-run", "version": 1})

    service, store = service_with(agent_graph(), execute)
    paused = asyncio.run(service._drive(store.row))
    data = paused["data"]
    assert data["status"] == "awaiting_confirmation"
    assert data["pending_node"] == "a"
    assert [item["node"] for item in data["pending_children"]] == ["a", "b"]
    confirmed = asyncio.run(service.confirm(paused["id"], paused["version"], True))
    assert confirmed["data"]["status"] == "completed"
    assert confirmed["data"]["node_status"] == {"input": "completed", "a": "completed", "b": "completed"}
    assert confirmed["data"]["pending_children"] == []
    assert [call[0] for call in service.runtime.calls] == ["a-run", "b-run"]
