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
