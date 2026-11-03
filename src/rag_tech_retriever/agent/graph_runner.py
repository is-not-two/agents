"""通用 DAG 工作流执行器：版本冻结、节点级重试、人工确认与多 Agent 串并行编排。"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter

import anyio

from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.workflow_graph import resolve, validate_graph_workflow
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Pause(Exception):
    """A node needs explicit human approval before continuing."""

    def __init__(self, kind: str, node: str, child: dict | None = None) -> None:
        self.kind, self.node, self.child = kind, node, child


class GraphWorkflowService:
    """Runs one frozen DAG per record; child agent runs are auditable separately."""

    def __init__(self, store: RecordStore, search, capabilities, runtime) -> None:
        self.store, self.search, self.capabilities, self.runtime = store, search, capabilities, runtime

    def check(self, payload: dict) -> dict:
        data = validate_graph_workflow(payload)
        references = {node.get("agent_id") for node in data["nodes"] if node.get("agent_id")}
        if data["agent_id"]:
            references.add(data["agent_id"])
        for agent_id in references:
            self.runtime.agent(agent_id)
        for node in data["nodes"]:
            if node["type"] in {"retrieve", "tool", "agent"} and not (node.get("agent_id") or data["agent_id"]):
                raise DomainError(f"节点 {node['id']} 需要 Agent 或默认 Agent")
        return data

    async def run(self, workflow_id: str, version: int, payload: dict) -> dict:
        workflow = self.store.get(workflow_id)
        if workflow["kind"] != "workflow":
            raise RecordMissing("流程不存在")
        if workflow["version"] != version:
            raise VersionConflict("流程配置已更新，请刷新后执行")
        cfg = self.check(workflow["data"])
        if not isinstance(payload, dict) or len(json.dumps(payload, ensure_ascii=False)) > 20000:
            raise DomainError("工作流输入必须为大小受限的对象")
        snapshots = {}
        for agent_id in {node.get("agent_id") or cfg["agent_id"] for node in cfg["nodes"]}:
            if not agent_id:
                continue
            live = self.runtime.agent(agent_id)
            snapshots[agent_id] = {"id": agent_id, "version": live["version"],
                                   "data": validate_agent(live["data"])}
        row = self.store.save("workflow_run", {
            "title": cfg["title"], "workflow_id": workflow_id, "kind": "graph",
            "status": "running", "started_at": _now(), "input": deepcopy(payload),
            "workflow": workflow, "agent_snapshots": snapshots,
            "steps": [], "node_outputs": {}, "node_status": {}, "pending_node": "",
            "pending_kind": "", "pending_child": None, "approved_nodes": [],
            "result": {"answer": "", "notes": []},
        })
        return await self._drive(row)

    async def confirm(self, run_id: str, version: int, approve: bool) -> dict:
        row = self.store.get(run_id)
        if row["kind"] != "workflow_run" or row["data"].get("kind") != "graph":
            raise RecordMissing("图工作流运行不存在")
        if row["version"] != version or row["data"]["status"] != "awaiting_confirmation":
            raise VersionConflict("运行已处理或版本改变，请重新读取")
        data = deepcopy(row["data"])
        if data["pending_kind"] == "agent" and data.get("pending_child"):
            child = data["pending_child"]
            result = await self.runtime.confirm(child["run_id"], child["version"], approve)
            if result["data"]["status"] == "awaiting_confirmation":
                data["pending_child"] = {"run_id": child["run_id"], "version": result["version"]}
                return self._save(row, data)
            if not approve or result["data"]["status"] == "failed":
                data["node_status"][data["pending_node"]] = "failed"
                data["result"]["notes"].append(f"节点 {data['pending_node']} 的子 Agent 未完成")
            else:
                data["node_outputs"][data["pending_node"]] = {
                    "run_id": child["run_id"], "answer": result["data"]["result"].get("answer", ""),
                    "notes": result["data"]["result"].get("notes", []),
                }
                data["node_status"][data["pending_node"]] = "completed"
        else:
            node_id = data["pending_node"]
            if approve:
                data["approved_nodes"].append(node_id)
                data["node_status"][node_id] = "completed"
                data["node_outputs"][node_id] = {"approved": True}
            else:
                data["node_status"][node_id] = "failed"
                data["result"]["notes"].append(f"用户拒绝了节点 {node_id}")
        data.update(pending_node="", pending_kind="", pending_child=None, status="running")
        row = self._save(row, data)
        return await self._drive(row)

    def _save(self, row: dict, data: dict) -> dict:
        return self.store.save(row["kind"], data, row["id"], row["version"])

    def _agent(self, data: dict, node: dict) -> dict:
        agent_id = node.get("agent_id") or data["workflow"]["data"].get("agent_id")
        snapshot = data.get("agent_snapshots", {}).get(agent_id)
        if not snapshot:
            raise DomainError("节点 Agent 快照缺失，请重新运行")
        live = self.runtime.agent(agent_id)
        if live["version"] != snapshot["version"] or validate_agent(live["data"]) != snapshot["data"]:
            raise DomainError("Agent 配置已变化，请重新运行工作流")
        return snapshot

    async def _execute_node(self, data: dict, node: dict) -> dict:
        context = {"input": data["input"], "nodes": data["node_outputs"]}
        kind = node["type"]
        if kind == "input":
            return {"input": deepcopy(data["input"])}
        if kind == "approval":
            raise _Pause("approval", node["id"])
        if kind == "retrieve":
            agent = self._agent(data, node)["data"]
            query = resolve(node.get("query") or "{{input.query}}", context, "检索模板")
            if not isinstance(query, str) or not query.strip():
                raise DomainError("检索节点查询不能为空")
            hits, notes = [], []
            for scope in agent["scopes"]:
                found = self.search.query(query, scope, agent["mode"])
                hits.extend(found["hits"])
                notes.extend(found["notes"])
            hits = hits[:node.get("limit", 5)]
            return {"query": query, "hits": hits, "notes": list(dict.fromkeys(notes))}
        if kind == "tool":
            agent = self._agent(data, node)
            specs, skills = await self.capabilities.catalog(agent["data"])
            spec = specs.get(node["tool_id"])
            if spec is None:
                raise DomainError(f"节点 {node['id']} 的工具未授权或不存在")
            if not spec["read_only"]:
                raise DomainError("工作流节点只能自动执行只读工具；写操作须走人工确认 Agent 会话")
            arguments = resolve(node.get("arguments", {}), context, "工具模板")
            return await self.capabilities.execute(spec, arguments, agent["data"], skills, False)
        if kind == "agent":
            agent = self._agent(data, node)
            query = resolve(node.get("query", ""), context, "Agent 指令")
            child = await self.runtime.start(agent["id"], agent["version"], query)
            if child["data"]["status"] == "awaiting_confirmation":
                raise _Pause("agent", node["id"], {"run_id": child["id"], "version": child["version"]})
            if child["data"]["status"] == "failed":
                raise DomainError(f"节点 {node['id']} 的 Agent 运行失败")
            return {"run_id": child["id"], "answer": child["data"]["result"].get("answer", ""),
                    "notes": child["data"]["result"].get("notes", [])}
        if kind == "merge":
            texts = []
            for source in self._predecessors(data, node["id"]):
                value = data["node_outputs"].get(source, {})
                for key in ("answer", "text"):
                    if isinstance(value.get(key), str) and value[key].strip():
                        texts.append(value[key].strip())
            return {"answer": "\n\n".join(texts)}
        raise DomainError("工作流节点类型不支持")

    def _predecessors(self, data: dict, node_id: str) -> list[str]:
        return [source for source, target in data["workflow"]["data"]["edges"] if target == node_id]

    async def _drive(self, row: dict) -> dict:
        data = deepcopy(row["data"])
        cfg = data["workflow"]["data"]
        nodes = {node["id"]: node for node in cfg["nodes"]}
        terminal_answers: list[str] = []
        while True:
            done = {key for key, value in data["node_status"].items() if value in {"completed", "skipped", "failed"}}
            ready = []
            for node_id, node in nodes.items():
                if node_id in done:
                    continue
                predecessors = self._predecessors(data, node_id)
                if all(data["node_status"].get(source) in {"completed", "skipped"} for source in predecessors):
                    ready.append(node)
            if not ready:
                break
            # Deterministic order: input first, then declaration order.
            ready.sort(key=lambda node: (node["type"] != "input", cfg["nodes"].index(node)))
            node = ready[0]
            if node["type"] == "approval" and node["id"] not in data["approved_nodes"]:
                data.update(status="awaiting_confirmation", pending_node=node["id"], pending_kind="approval")
                return self._save(row, data)
            data["node_status"][node["id"]] = "running"
            self._save(row, data)
            started = perf_counter()
            try:
                with anyio.fail_after(cfg["node_timeout_seconds"]):
                    output = await self._execute_node(data, node)
                data["node_outputs"][node["id"]] = output
                data["node_status"][node["id"]] = "completed"
                data["steps"].append({"key": node["id"], "title": node["id"], "status": "completed",
                                      "detail": json.dumps(output, ensure_ascii=False)[:10000],
                                      "duration_ms": round((perf_counter() - started) * 1000)})
                terminal = not any(edge[0] == node["id"] for edge in cfg["edges"])
                if terminal and isinstance(output.get("answer"), str):
                    terminal_answers.append(output["answer"])
            except _Pause as pause:
                data.update(status="awaiting_confirmation", pending_node=pause.node,
                            pending_kind=pause.kind, pending_child=pause.child)
                return self._save(row, data)
            except DomainError as exc:
                data["node_status"][node["id"]] = "failed"
                data["result"]["notes"].append(str(exc))
                data["steps"].append({"key": node["id"], "title": node["id"], "status": "failed",
                                      "detail": str(exc), "duration_ms": round((perf_counter() - started) * 1000)})
            row = self._save(row, data)
        failed = any(value == "failed" for value in data["node_status"].values())
        data["result"]["answer"] = "\n\n".join(terminal_answers) or data["result"].get("answer", "")
        data["status"] = "failed" if failed else ("fallback" if data["result"]["notes"] else "completed")
        data["finished_at"] = _now()
        return self._save(row, data)
