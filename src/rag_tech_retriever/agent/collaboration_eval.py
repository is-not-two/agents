"""Same-input deterministic fixed/single/collaboration comparison, not model quality."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import anyio

from rag_tech_retriever.agent.capability_runtime import AgentRuntime
from rag_tech_retriever.agent.collaboration import CollaborationService
from rag_tech_retriever.agent.evaluation import _Store, evaluate_suite, load_suite
from rag_tech_retriever.agent.workflow_service import WorkflowService
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.platform.agent_capabilities import DEFAULT_LIMITS, object_schema
from rag_tech_retriever.platform.mcp_client import ToolError


def _call(name: str, arguments: dict, identity: str) -> dict:
    return {"id": identity, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class _ReadBoundary:
    def __init__(self, task: dict) -> None:
        self.task, self.limits, self.model_aliases, self.executed = task, dict(DEFAULT_LIMITS), {}, []

    async def catalog(self, profile: dict) -> tuple[dict, list]:
        return ({"lookup": {"name": "lookup", "read_only": True, "description": "Fixture readonly source",
                "input_schema": object_schema({}, [])}} if "lookup" in profile.get("tool_ids", []) else {}), []

    async def execute(self, spec: dict, arguments: dict, profile: dict, skills: list, approved: bool) -> dict:
        if spec["name"] != "lookup" or "lookup" not in profile.get("tool_ids", []):
            raise ToolError("Fixture tool not authorized")
        self.executed.append("lookup")
        return {"source": "synthetic fixture", "content": self.task["source"]}


def _profile(title: str, **extra) -> dict:
    return validate_agent({"title": title, "generate": True, "scopes": ["personal"], **extra})


def _measure(task: dict, mode: str) -> dict:
    store, caps = _Store(), _ReadBoundary(task)
    expected = task["source"] + " [fixture-source]"
    digest = hashlib.sha256(task["task"].encode()).hexdigest()
    observed = {"models": 0, "reads": 0}
    started = perf_counter()
    if mode == "fixed":
        class Search:
            def query(self, query, scope, method):
                assert query == task["task"]; observed["reads"] += 1
                return {"hits": [{"id": task["id"], "title": "Fixture source", "content": task["source"],
                                  "source": "synthetic", "category": "personal"}], "notes": [], "engine": "fixture"}

            def generate_answer(self, query, hits, prompt):
                assert query == task["task"] and hits[0]["content"] == task["source"]
                observed["models"] += 1
                return expected, []

        owner = store.save("agent_profile", _profile("Fixed template"))
        flow = store.save("workflow", {"title": "Fixed", "kind": "answer", "agent_id": owner["id"]})
        run = WorkflowService(store, Search()).run(flow["id"], 1, {"query": task["task"]})
        tool_attempts, approvals = 0, 0
    elif mode == "single":
        owner = store.save("agent_profile", _profile("Single", tool_ids=["lookup"]))
        runtime = AgentRuntime(store, None, caps)

        async def model(messages, specs):
            observed["models"] += 1
            if observed["models"] == 1:
                assert messages[1]["content"] == task["task"]
                return {"tool_calls": [_call("lookup", {}, "source")], "content": None}
            assert task["anchor"] in json.dumps(messages, ensure_ascii=False)
            return {"content": expected}

        runtime.model_chat = model
        run = anyio.run(runtime.start, owner["id"], 1, task["task"])
        tool_attempts, approvals = run["data"]["calls_used"], 0
        observed["reads"] = len(caps.executed)
    else:
        draft = store.save("agent_profile", _profile("Draft worker", system_prompt="Draft from actual source"))
        review = store.save("agent_profile", _profile("Review worker", system_prompt="Check evidence, do not invent"))
        owner = store.save("agent_profile", _profile("Retrieval supervisor", tool_ids=["lookup"],
            handoffs={"allowed": [draft["id"], review["id"]]}))
        plan = [{"step": i, "assignee": row["id"], "input": task["task"], "expected": "Preserve source and constraints"}
                for i, row in enumerate([draft, review])]
        counts = {}

        def factory(actor):
            async def model(messages, specs):
                index = counts.get(actor, 0); counts[actor] = index + 1; observed["models"] += 1
                if actor == owner["id"]:
                    if index == 0:
                        assert messages[1]["content"] == task["task"]
                        return {"content": None, "tool_calls": [_call("lookup", {}, "source"), _call("propose_plan", {"plan": plan}, "plan")]}
                    if index < 3:
                        return {"content": None, "tool_calls": [_call("call_worker", {"step": index - 1}, "dispatch" + str(index))]}
                    assert task["anchor"] in json.dumps(messages, ensure_ascii=False)
                    return {"content": expected}
                assert task["anchor"] in json.dumps(messages, ensure_ascii=False), "Worker did not receive actual source/blackboard"
                return {"content": json.dumps({"status": "done", "content": expected}, ensure_ascii=False)}
            return model

        with TemporaryDirectory(prefix="collab-fixture-") as temp:
            service = CollaborationService(Path(temp), store, None, caps, factory)
            service.config["enabled"] = True
            pending = anyio.run(service.start, owner["id"], 1, task["task"])
            assert pending["data"]["status"] == "awaiting_confirmation" and observed["models"] == 1
            run = anyio.run(service.confirm, pending["id"], pending["version"], True)
        budget = run["data"]["shared_state"]["budget"]
        assert budget["model_used"] == observed["models"]
        tool_attempts, approvals = budget["tool_used"], 1
        observed["reads"] = len(caps.executed)
    data = run["data"]
    return {"mode": mode, "input_sha256": digest, "status": data["status"],
        "anchor_passed": task["anchor"] in data["result"]["answer"],
        "answer_sha256": hashlib.sha256(data["result"]["answer"].encode()).hexdigest(),
        "model_boundary_calls": observed["models"], "tool_attempts": tool_attempts,
        "readonly_source_queries": observed["reads"], "confirmation_protocol_events": approvals,
        "confirmation_source": "fixture-auto-approval" if approvals else "none",
        "human_edits": None, "usage": "unknown", "cost": "unknown",
        "duration_ms": round((perf_counter() - started) * 1000, 3)}


def compare(task_path: Path, r0_path: Path) -> dict:
    """Keep original R0 guards intact; disclose incompatible tasks rather than rewrite them."""
    raw = task_path.read_bytes(); definition = json.loads(raw)
    suite, r0_hash = load_suite(r0_path)
    if definition.get("schema") != 1 or definition.get("r0_sha256") != r0_hash or len(definition.get("tasks", [])) != 10:
        raise ValueError("Comparison fixture/version does not match frozen R0 suite")
    by_id = {item["id"]: item for item in suite["cases"]}
    records = []
    for task in definition["tasks"]:
        if task["r0_case_id"]:
            assert task["task"] == by_id[task["r0_case_id"]]["task"], "Do not rewrite R0 input"
        modes = [_measure(deepcopy(task), name) for name in ("fixed", "single", "collaboration")]
        assert len({mode["input_sha256"] for mode in modes}) == 1
        records.append({"id": task["id"], "r0_case_id": task["r0_case_id"], "modes": modes,
                        "passed": all(mode["status"] == "completed" and mode["anchor_passed"] for mode in modes)})
    r0_guard = evaluate_suite(r0_path)
    common = {item["r0_case_id"] for item in definition["tasks"] if item["r0_case_id"]}
    sources = ["capability_runtime.py", "collaboration.py", "workflow_service.py", "collaboration_eval.py"]
    return {"schema": 1, "task_version": definition["version"], "task_sha256": hashlib.sha256(raw).hexdigest(),
        "runtime_sources": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources},
        "r0_guard": r0_guard,
        "r0_compatibility": [{"id": case["id"], "common_comparison": case["id"] in common,
            "reason": "same readonly retrieval task" if case["id"] in common else
                "not a common readonly retrieval contract; original permission/failure assertions still run in R0 guard"} for case in suite["cases"]],
        "cases": records, "passed": r0_guard["passed"] and all(record["passed"] for record in records),
        "measured_scope": "scripted model/tool/store boundaries with real runtimes; timing is orchestration overhead, not real provider latency",
        "quality_verified": False, "human_edits_measured": False, "real_provider_used": False,
        "usage": "unknown", "cost": "unknown", "recommendation": "keep_disabled_pending_real_quality",
        "finding": "Same scripted artifacts show no quality gain; collaboration requires more model calls and a confirmation. No evidence justifies C-full/DAG expansion."}
