"""通用 DAG 工作流执行器：版本冻结、并行调度、节点级隔离、人工确认与多 Agent 编排。"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter

import anyio

from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.workflow_graph import resolve, validate_graph_workflow
from rag_tech_retriever.platform.mcp_client import ToolError
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
            "steps": [], "node_outputs": {}, "node_status": {}, "node_attempts": {},
            "pending_node": "", "pending_kind": "", "pending_child": None, "pending_children": [],
            "approved_nodes": [],
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
            # 并行 Agent 可能同时进入待确认；逐个确认，未完成的保留在 pending_children。
            children = data.get("pending_children") or [
                {"node": data["pending_node"], **data["pending_child"]}
            ]
            remaining = []
            for item in children:
                node_id = item["node"]
                result = await self.runtime.confirm(item["run_id"], item["version"], approve)
                if result["data"]["status"] == "awaiting_confirmation":
                    remaining.append({"node": node_id, "run_id": item["run_id"],
                                      "version": result["version"]})
                    continue
                if not approve or result["data"]["status"] == "failed":
                    data["node_status"][node_id] = "failed"
                    data["result"]["notes"].append(f"节点 {node_id} 的子 Agent 未完成")
                else:
                    data["node_outputs"][node_id] = {
                        "run_id": item["run_id"], "answer": result["data"]["result"].get("answer", ""),
                        "notes": result["data"]["result"].get("notes", []),
                    }
                    data["node_status"][node_id] = "completed"
            if remaining:
                first = remaining[0]
                data.update(status="awaiting_confirmation", pending_node=first["node"],
                            pending_kind="agent", pending_children=remaining,
                            pending_child={"run_id": first["run_id"], "version": first["version"]})
                return self._save(row, data)
        else:
            node_id = data["pending_node"]
            if approve:
                data["approved_nodes"].append(node_id)
                data["node_status"][node_id] = "completed"
                data["node_outputs"][node_id] = {"approved": True}
            else:
                data["node_status"][node_id] = "failed"
                data["result"]["notes"].append(f"用户拒绝了节点 {node_id}")
        data.update(pending_node="", pending_kind="", pending_child=None,
                    pending_children=[], status="running")
        row = self._save(row, data)
        return await self._drive(row)

    async def resume(self, run_id: str, version: int) -> dict:
        """恢复崩溃后停在 running 的只读节点；Agent/审批节点必须先人工预检。"""
        row = self.store.get(run_id)
        if row["kind"] != "workflow_run" or row["data"].get("kind") != "graph":
            raise RecordMissing("图工作流运行不存在")
        if row["version"] != version:
            raise VersionConflict("运行记录已变化，请刷新后重试")
        data = deepcopy(row["data"])
        if data.get("status") != "running":
            raise DomainError("只有运行中的图工作流可以恢复")
        if data.get("pending_node"):
            raise DomainError("该运行等待人工确认，请使用确认接口")
        cfg = data["workflow"]["data"]
        running_ids = {node_id for node_id, status in data["node_status"].items()
                       if status == "running"}
        unsafe = [node["id"] for node in cfg["nodes"]
                  if node["id"] in running_ids and node["type"] == "agent"]
        if unsafe:
            raise DomainError(
                f"节点 {','.join(unsafe)} 为 Agent 节点，可能已产生副作用，需人工预检后再恢复")
        for node_id in running_ids:
            data["node_status"][node_id] = ""
        if running_ids:
            data.setdefault("recovery", []).append(
                {"at": _now(), "nodes": sorted(running_ids), "reason": "崩溃后只读节点重排"})
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
                # 向量检索是同步阻塞调用；放到线程池，避免并行波次被单节点卡住事件循环。
                found = await anyio.to_thread.run_sync(
                    self.search.query, query, scope, agent["mode"])
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

    async def _run_node(self, data: dict, node: dict) -> dict:
        """执行单个节点；只对声明过的瞬时错误重试，避免重复写操作或重复审批。"""
        cfg = data["workflow"]["data"]
        retry = node.get("retry", {})
        # Agent 可能已产生副作用：默认不重试，只有显式配置 retry 才允许。
        default_attempts = 1 if node["type"] == "agent" else cfg["max_retries"] + 1
        max_attempts = retry.get("max_attempts", default_attempts)
        backoff_ms = retry.get("backoff_ms", 500)
        retry_on = set(retry.get("retry_on", ["timeout", "tool_error"]))
        timeout = node.get("timeout_s", cfg["node_timeout_seconds"])
        attempts: list[dict] = []
        for attempt in range(1, max_attempts + 1):
            started = perf_counter()
            try:
                with anyio.fail_after(timeout):
                    output = await self._execute_node(data, node)
                attempts.append({"attempt": attempt, "status": "completed",
                                 "duration_ms": round((perf_counter() - started) * 1000)})
                return {"status": "completed", "output": output, "attempts": attempts,
                        "duration_ms": round((perf_counter() - started) * 1000)}
            except _Pause as pause:
                attempts.append({"attempt": attempt, "status": "paused",
                                 "duration_ms": round((perf_counter() - started) * 1000)})
                return {"status": "paused", "pause": pause, "attempts": attempts,
                        "duration_ms": round((perf_counter() - started) * 1000)}
            except (DomainError, ToolError) as exc:
                category = "tool_error" if isinstance(exc, ToolError) else "domain_error"
                attempts.append({"attempt": attempt, "status": "failed", "error": str(exc),
                                 "duration_ms": round((perf_counter() - started) * 1000)})
                if category in retry_on and attempt < max_attempts:
                    await asyncio.sleep(backoff_ms / 1000 * (2 ** (attempt - 1)))
                    continue
                return {"status": "failed", "error": str(exc), "attempts": attempts,
                        "duration_ms": round((perf_counter() - started) * 1000)}
            except (TimeoutError, asyncio.TimeoutError):
                attempts.append({"attempt": attempt, "status": "failed",
                                 "error": f"节点 {node['id']} 执行超时",
                                 "duration_ms": round((perf_counter() - started) * 1000)})
                if "timeout" in retry_on and attempt < max_attempts:
                    await asyncio.sleep(backoff_ms / 1000 * (2 ** (attempt - 1)))
                    continue
                return {"status": "failed", "error": f"节点 {node['id']} 执行超时",
                        "attempts": attempts,
                        "duration_ms": round((perf_counter() - started) * 1000)}
        raise AssertionError("unreachable retry loop")  # pragma: no cover

    def _ready_nodes(self, data: dict, nodes: dict, order: dict, join_policy: str) -> list[dict]:
        """按依赖与汇合策略计算当前可执行节点，返回确定性顺序。"""
        satisfiable = {"completed", "skipped", "fallback"}
        done = {key for key, value in data["node_status"].items()
                if value in satisfiable | {"failed", "running"}}
        ready = []
        for node_id, node in nodes.items():
            if node_id in done:
                continue
            predecessors = self._predecessors(data, node_id)
            statuses = [data["node_status"].get(source) for source in predecessors]
            if not predecessors:
                satisfied = True
            elif join_policy == "any_success":
                satisfied = any(value in satisfiable for value in statuses)
            else:
                satisfied = all(value in satisfiable for value in statuses)
            if satisfied:
                ready.append(node)
        ready.sort(key=lambda node: (node["type"] != "input", order[node["id"]]))
        return ready

    def _apply_outcome(self, data: dict, node: dict, outcome: dict) -> bool:
        """写入单节点结果；返回该节点是否进入待确认。"""
        attempts = outcome.get("attempts", [])
        data.setdefault("node_attempts", {})[node["id"]] = attempts
        if outcome["status"] == "paused":
            return True
        if outcome["status"] == "completed":
            data["node_outputs"][node["id"]] = outcome["output"]
            data["node_status"][node["id"]] = "completed"
            data["steps"].append({"key": node["id"], "title": node["id"],
                                  "status": "completed",
                                  "detail": json.dumps(outcome["output"], ensure_ascii=False)[:10000],
                                  "duration_ms": outcome["duration_ms"]})
            return False
        on_error = node.get("on_error", "fail")
        if on_error == "continue":
            data["node_status"][node["id"]] = "skipped"
            data["result"]["notes"].append(f"节点 {node['id']} 已按失败策略跳过：{outcome['error']}")
            data["steps"].append({"key": node["id"], "title": node["id"],
                                  "status": "skipped", "detail": outcome["error"],
                                  "duration_ms": outcome["duration_ms"]})
        elif on_error == "fallback":
            data["node_outputs"][node["id"]] = deepcopy(node.get("fallback", {}))
            data["node_status"][node["id"]] = "fallback"
            data["result"]["notes"].append(f"节点 {node['id']} 已使用回退结果：{outcome['error']}")
            data["steps"].append({"key": node["id"], "title": node["id"],
                                  "status": "fallback",
                                  "detail": json.dumps(node.get("fallback", {}), ensure_ascii=False)[:10000],
                                  "duration_ms": outcome["duration_ms"]})
        else:
            data["node_status"][node["id"]] = "failed"
            data["result"]["notes"].append(outcome["error"])
            data["steps"].append({"key": node["id"], "title": node["id"],
                                  "status": "failed", "detail": outcome["error"],
                                  "duration_ms": outcome["duration_ms"]})
        return False

    async def _drive(self, row: dict) -> dict:
        data = deepcopy(row["data"])
        cfg = data["workflow"]["data"]
        nodes = {node["id"]: node for node in cfg["nodes"]}
        order = {node["id"]: index for index, node in enumerate(cfg["nodes"])}
        terminal_ids = [node["id"] for node in cfg["nodes"]
                        if not any(edge[0] == node["id"] for edge in cfg["edges"])]
        join_policy = cfg.get("join_policy", "all_success")
        satisfiable = {"completed", "skipped", "fallback"}
        running: dict[asyncio.Task, dict] = {}
        pauses: list[tuple[dict, dict]] = []
        pause_requested = False
        try:
            while True:
                if not pause_requested:
                    ready = self._ready_nodes(data, nodes, order, join_policy)
                    runnable = [node for node in ready if node["type"] != "approval"]
                    # 动态补位：任一节点完成即释放槽位，不再等整波结束。
                    started = False
                    while runnable and len(running) < cfg["max_parallel"]:
                        node = runnable.pop(0)
                        data["node_status"][node["id"]] = "running"
                        snapshot = deepcopy(data)
                        task = asyncio.create_task(self._run_node(snapshot, node))
                        running[task] = node
                        started = True
                    if started:
                        row = self._save(row, data)
                    if not running:
                        approvals = [node for node in self._ready_nodes(
                            data, nodes, order, join_policy) if node["type"] == "approval"]
                        if approvals:
                            gate = approvals[0]
                            data.update(status="awaiting_confirmation", pending_node=gate["id"],
                                        pending_kind="approval")
                            return self._save(row, data)
                        break
                if not running:
                    break
                done, _ = await asyncio.wait(list(running.keys()),
                                             return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(done, key=lambda item: order[running[item]["id"]]):
                    node = running.pop(task)
                    outcome = task.result()
                    if self._apply_outcome(data, node, outcome):
                        pauses.append((node, outcome))
                        pause_requested = True
                row = self._save(row, data)
                if pause_requested and not running:
                    first, first_outcome = pauses[0]
                    pause = first_outcome["pause"]
                    children = [{"node": node["id"], **outcome["pause"].child}
                                for node, outcome in pauses if outcome["pause"].child]
                    data.update(status="awaiting_confirmation", pending_node=first["id"],
                                pending_kind=pause.kind, pending_child=pause.child,
                                pending_children=children)
                    return self._save(row, data)
        finally:
            if running:
                for task in running:
                    task.cancel()
                await asyncio.gather(*running.keys(), return_exceptions=True)
        failed = any(value == "failed" for value in data["node_status"].values())
        terminal_succeeded = any(data["node_status"].get(node_id) in satisfiable
                                 for node_id in terminal_ids)
        answers = []
        for node_id in terminal_ids:
            output = data["node_outputs"].get(node_id, {})
            if isinstance(output.get("answer"), str) and output["answer"].strip():
                answers.append(output["answer"])
        data["result"]["answer"] = "\n\n".join(answers) or data["result"].get("answer", "")
        if failed and not (join_policy == "any_success" and terminal_succeeded):
            data["status"] = "failed"
        else:
            data["status"] = "fallback" if (failed or data["result"]["notes"]) else "completed"
        data["finished_at"] = _now()
        data.update(pending_node="", pending_kind="", pending_child=None, pending_children=[])
        return self._save(row, data)
