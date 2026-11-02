"""LangGraph 固定流程执行：版本化配置、可审计步骤及原子人工确认入库。"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from rag_tech_retriever.agent.capability_runtime import effective_limits
from rag_tech_retriever.agent.memory import AgentMemory
from rag_tech_retriever.common.provider import GENERATION_POLICY
from rag_tech_retriever.domains.automation import validate_agent, validate_workflow
from rag_tech_retriever.domains.knowledge import validate_knowledge
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.agent_capabilities import DEFAULT_LIMITS
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict
from rag_tech_retriever.platform.search_service import SearchService


class FlowState(TypedDict, total=False):
    """本次调用私有状态，不使用跨用户全局记忆。"""

    run: dict


def split_document(content: str, title: str, source: str, size: int) -> list[dict]:
    """按 Markdown 标题和字数切分，不自动生成或归类；每段可人工复核。"""
    sections: list[tuple[str, str]] = []
    heading, lines = title, []
    fenced = False
    for line in content.splitlines():
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
        match = None if fenced else re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            if "\n".join(lines).strip():
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = match.group(1), []
        else:
            lines.append(line)
    if "\n".join(lines).strip():
        sections.append((heading, "\n".join(lines).strip()))
    chunks = []
    for heading, body in sections:
        pieces = [body[i:i + size] for i in range(0, len(body), size)]
        for index, piece in enumerate(pieces, 1):
            chunks.append(validate_knowledge({
                "title": heading[:140] + (f" · {index}" if len(pieces) > 1 else ""),
                "content": piece, "source": source, "tags": [],
            }))
    if not chunks:
        raise DomainError("文件只有标题，没有可入库正文")
    if len(chunks) > 500:
        raise DomainError("片段超过 500 个，请分批处理资料")
    return chunks


class WorkflowService:
    """编排层调用原子检索/切片与通用存储，API 不参与执行细节。"""

    def __init__(self, store: RecordStore, search: SearchService, capabilities=None) -> None:
        self.store, self.search = store, search
        self.capabilities = capabilities
        self.graphs = {}
        for kind, steps in {
            "answer": [("input", self._input), ("retrieve", self._retrieve), ("generate", self._generate)],
            "ingest": [("input", self._input), ("parse", self._parse)],
        }.items():
            graph = StateGraph(FlowState)
            previous = START
            for key, operation in steps:
                graph.add_node(key, self._step(key, operation))
                graph.add_edge(previous, key)
                previous = key
            graph.add_edge(previous, END)
            self.graphs[kind] = graph.compile()

    def setup(self) -> dict:
        """用户明确启用时才创建三条基础配置；事务锁使重复点击幂等。"""
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":setup",))
            cur.execute(
                f"SELECT id FROM {self.store.records} "
                "WHERE kind='workflow' AND NOT deleted LIMIT 1"
            )
            if cur.fetchone():
                return {"created": False}
            agent = self.store._save(cur, "agent_profile", validate_agent({
                "title": "知识检索助手", "system_prompt": "先回答核心问题，再用 [1] 等编号引用依据；没有依据时说明缺口。"
            }), uuid4().hex, None)
            for data in (
                {"title": "知识检索与回答", "kind": "answer", "agent_id": agent["id"]},
                {"title": "资料整理与入库", "kind": "ingest"},
            ):
                self.store._save(cur, "workflow", validate_workflow(data), uuid4().hex, None)
            return {"created": True}

    def agent(self, record_id: str) -> dict:
        """防止把其他记录类型当成 Agent。"""
        row = self.store.get(record_id)
        if row["kind"] != "agent_profile":
            raise RecordMissing("Agent 不存在")
        return row

    def check_workflow(self, data: dict) -> dict:
        """引用必须是当前有效 Agent，执行时还会重新读取其版本。"""
        data = validate_workflow(data)
        if data["kind"] == "answer":
            self.agent(data["agent_id"])
        return data

    def run(self, workflow_id: str, version: int, payload: dict) -> dict:
        """冻结实际配置版本；每步保存，异常产生可追查失败结果。"""
        workflow = self.store.get(workflow_id)
        if workflow["kind"] != "workflow":
            raise RecordMissing("流程不存在")
        if workflow["version"] != version:
            raise VersionConflict("流程配置已更新，请刷新后执行")
        cfg = self.check_workflow(workflow["data"])
        kind = cfg["kind"]
        if kind == "answer":
            inputs = {"query": text(payload.get("query", ""), "问题", 1000, True)}
            agent = self.agent(cfg["agent_id"])
            agent = {**agent, "data": validate_agent(agent["data"])}
        else:
            inputs = {
                "title": text(payload.get("title", ""), "资料名称", 160, True),
                "source": text(payload.get("source", ""), "来源", 1000),
                "content": text(payload.get("content", ""), "资料正文", 100000, True),
            }
            agent = None
        private = agent is not None and agent["data"]["memory"]["scope"] != "none"
        row = self.store.save("agent_session" if private else "workflow_run", {
            "title": cfg["title"], "workflow_id": workflow_id, "kind": kind,
            "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
            "input": inputs, "workflow": workflow, "agent": agent,
            "steps": [], "result": {},
        })
        return self._execute(kind, row)

    def preview_markdown(self, filename: str, content: str, chunk_size: int = 1500) -> dict:
        """Uploaded Markdown uses the existing parse/confirm transaction, no LLM required."""
        title = text(filename, "文件名称", 160, True)
        content = text(content, "资料正文", 100000, True)
        workflow = {"id": "markdown-upload", "version": 1, "data": {
            "title": title, "kind": "ingest", "chunk_size": chunk_size,
        }}
        row = self.store.save("workflow_run", {"title": title, "workflow_id": "markdown-upload",
            "kind": "ingest", "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
            "input": {"title": title, "content": content, "source": "upload:" + title},
            "workflow": workflow, "agent": None, "steps": [], "result": {}})
        return self._execute("ingest", row)

    def _execute(self, kind: str, row: dict) -> dict:
        result = self.graphs[kind].invoke({"run": row})["run"]
        if result["data"]["status"] == "running":
            data = deepcopy(result["data"])
            data["status"] = "awaiting_confirmation" if kind == "ingest" else (
                "fallback" if data["result"].get("notes") else "completed"
            )
            data["finished_at"] = datetime.now(timezone.utc).isoformat()
            result = self.store.save(result["kind"], data, result["id"], result["version"])
        return result

    def _step(self, key: str, operation):
        def execute(state: FlowState) -> dict:
            row = state["run"]
            if row["data"]["status"] != "running":
                return {"run": row}
            data, start = deepcopy(row["data"]), perf_counter()
            data["run_id"] = row["id"]
            try:
                label, detail, outcome = operation(data)
            except (DomainError, ValueError, RuntimeError, OSError) as exc:
                # 错误文案只暴露领域错误，底层异常不泄漏密钥和堆栈。
                label, detail, outcome = key, str(exc) if isinstance(exc, DomainError) else "该步骤未完成，请重试", "failed"
                data["status"] = "failed"
                data["finished_at"] = datetime.now(timezone.utc).isoformat()
            data["steps"].append({"key": key, "title": label, "status": outcome,
                                  "detail": detail, "duration_ms": round((perf_counter() - start) * 1000)})
            saved = self.store.save(row["kind"], data, row["id"], row["version"])
            return {"run": saved}
        return execute

    def _input(self, data: dict) -> tuple[str, str, str]:
        return "接收输入", "输入已校验，执行配置版本已保存", "completed"

    def _retrieve(self, data: dict) -> tuple[str, str, str]:
        self._check_agent(data)
        agent = data["agent"]["data"]
        hits, notes, engines = [], [], []
        for scope in agent["scopes"]:
            found = self.search.query(data["input"]["query"], scope, agent["mode"])
            hits.extend(found["hits"])
            notes.extend(found["notes"])
            engines.append(found["engine"])
        # 不混排不同引擎的分数，按范围轮流取，避免某一范围独占全部引用。
        categories = {scope: [h for h in hits if h["category"] == scope] for scope in agent["scopes"]}
        ordered = []
        for i in range(agent["result_limit"]):
            for scope in agent["scopes"]:
                if i < len(categories[scope]):
                    ordered.append(categories[scope][i])
        data["result"] = {"hits": ordered[:agent["result_limit"]], "answer": "",
                          "notes": list(dict.fromkeys(notes)), "engine": "；".join(dict.fromkeys(engines))}
        return "检索依据", f"找到 {len(data['result']['hits'])} 条引用", "fallback" if notes else "completed"

    def _generate(self, data: dict) -> tuple[str, str, str]:
        profile, result = data["agent"]["data"], data["result"]
        if not profile["generate"]:
            return "AI 回答", "Agent 未开启生成，保留检索引用", "skipped"
        if not result["hits"]:
            return "AI 回答", "没有检索依据，本次不生成回答", "skipped"
        self._check_agent(data)
        limits = effective_limits(self.capabilities.limits if self.capabilities else DEFAULT_LIMITS, profile)
        limits["max_tokens"] = min(limits["max_tokens"], getattr(self.search, "max_tokens", limits["max_tokens"]))
        limits["timeout_seconds"] = min(limits["timeout_seconds"], getattr(self.search, "timeout", limits["timeout_seconds"]))
        data["effective_limits"] = limits
        data.setdefault("trace", [])
        memory = self._memory(data)
        def check() -> None:
            self._check_agent(data)
            self._memory(data)
        token = GENERATION_POLICY.set({"limits": limits, "model": profile["model"],
            "context": profile["context"], "aliases": self.capabilities.model_aliases if self.capabilities else {},
            "trace": data["trace"], "parent": data["run_id"], "memory": memory, "before_request": check})
        try:
            answer, notes = self.search.generate_answer(data["input"]["query"], result["hits"], profile["system_prompt"])
        finally:
            GENERATION_POLICY.reset(token)
        result["answer"] = answer
        result["notes"].extend(notes)
        return "AI 回答", "回答已生成" if answer else "；".join(notes), "completed" if answer else "fallback"

    def _check_agent(self, data: dict) -> None:
        frozen = data["agent"]
        live = self.agent(frozen["id"])
        if live["version"] != frozen["version"] or validate_agent(live["data"]) != frozen["data"]:
            raise DomainError("Agent授权版本已变化，请新建运行")

    def _memory(self, data: dict) -> list:
        if data["agent"]["data"]["memory"]["scope"] != "persistent":
            return []
        limits = self.capabilities.limits if self.capabilities else DEFAULT_LIMITS
        facts, revision = AgentMemory(self.store, limits).context(data["agent"]["id"])
        if data.get("memory_revision", revision) != revision:
            raise DomainError("长期记忆已改变，请新建运行")
        data["memory_revision"] = revision
        data["memory_refs"] = [{"id": fact["id"], "version": fact["version"]} for fact in facts]
        return facts

    def _parse(self, data: dict) -> tuple[str, str, str]:
        inputs = data["input"]
        data["result"] = {"chunks": split_document(inputs["content"], inputs["title"], inputs["source"], data["workflow"]["data"]["chunk_size"])}
        return "解析与切片", f"生成 {len(data['result']['chunks'])} 个待确认片段，尚未写入知识库", "completed"

    def confirm(self, run_id: str, version: int, selected: list[int]) -> dict:
        """运行版本+原子批次确保重复确认不会重复入库。"""
        row = self.store.get(run_id)
        if row["kind"] != "workflow_run" or row["data"]["kind"] != "ingest":
            raise RecordMissing("入库预览不存在")
        if row["version"] != version or row["data"]["status"] != "awaiting_confirmation":
            raise VersionConflict("该预览已确认或更新，请刷新运行记录")
        chunks = row["data"]["result"]["chunks"]
        if not selected or len(set(selected)) != len(selected) or any(type(i) is not int or i < 0 or i >= len(chunks) for i in selected):
            raise DomainError("请选择有效且不重复的入库片段")
        data = deepcopy(row["data"])
        ids = [uuid4().hex for _ in selected]
        data["status"] = "confirmed"
        data["result"]["created_ids"] = ids
        data["result"]["selected"] = selected
        data["steps"].append({"key": "confirm", "title": "人工确认入库", "status": "completed",
                              "detail": f"已保存 {len(ids)} 条知识", "duration_ms": 0})
        items = [{"id": record_id, "kind": "knowledge", "data": validate_knowledge(chunks[index])}
                 for record_id, index in zip(ids, selected)]
        items.append({"id": row["id"], "kind": "workflow_run", "data": data, "version": version})
        return self.store.save_batch(items)[-1]
