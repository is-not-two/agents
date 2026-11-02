"""Offline contract evaluation of the real AgentRuntime; never a model-quality score."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import anyio

from rag_tech_retriever.agent.capability_runtime import AgentRuntime
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.agent_capabilities import DEFAULT_LIMITS
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict


class EvaluationError(ValueError):
    """Invalid evaluation data must block the gate, not yield an empty green report."""


def load_suite(path: Path) -> tuple[dict, str]:
    """Load bounded, versioned declarative fixtures; reject unknown or empty cases."""
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise EvaluationError("Suite exceeds 2 MB")
    suite = json.loads(raw)
    if not isinstance(suite, dict) or set(suite) != {"schema", "version", "cases"}:
        raise EvaluationError("Invalid suite envelope")
    if type(suite["schema"]) is not int or suite["schema"] != 1 or not isinstance(suite["version"], str) or not suite["version"]:
        raise EvaluationError("Unsupported suite version")
    cases = suite["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 500:
        raise EvaluationError("Suite needs 1–500 cases")
    seen = set()
    for case in cases:
        required = {"id", "task", "messages", "grants", "expect"}
        if not isinstance(case, dict) or not required <= set(case) or set(case) - required - {"confirm", "limits"}:
            raise EvaluationError("Invalid case fields")
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in seen:
            raise EvaluationError("Case IDs must be unique and nonempty")
        seen.add(case["id"])
        if not isinstance(case["task"], str) or not case["task"].strip():
            raise EvaluationError("Task is required")
        if not isinstance(case["messages"], list) or not case["messages"] or len(case["messages"]) > 20:
            raise EvaluationError("Bounded model script required")
        if not isinstance(case["grants"], list) or any(g not in {"lookup", "write", "explode", "oversize"} for g in case["grants"]):
            raise EvaluationError("Unknown fixture grant")
        if "confirm" in case and type(case["confirm"]) is not bool:
            raise EvaluationError("Confirmation must be boolean")
        limits = case.get("limits", {})
        if not isinstance(limits, dict) or any(k not in {"max_steps", "max_calls", "max_result_chars"} or type(v) is not int or not 1 <= v <= 16000 for k, v in limits.items()):
            raise EvaluationError("Unsafe evaluation limits")
        expected = case["expect"]
        if (not isinstance(expected, dict) or not {"status", "executed"} <= set(expected)
                or set(expected) - {"status", "executed", "answer_contains", "max_calls"}
                or not isinstance(expected["status"], str)
                or expected["status"] not in {"completed", "fallback", "failed", "awaiting_confirmation"}
                or not isinstance(expected["executed"], list)
                or any(not isinstance(x, str) for x in expected["executed"])
                or ("answer_contains" in expected and not isinstance(expected["answer_contains"], str))
                or ("max_calls" in expected and (type(expected["max_calls"]) is not int or expected["max_calls"] < 0))):
            raise EvaluationError("Invalid assertions")
    return suite, hashlib.sha256(raw).hexdigest()


class _Store:
    """Isolated versioned test adapter: no database, files, or user records."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, key: str) -> dict:
        if key not in self.rows:
            raise RecordMissing("Fixture record not found")
        return deepcopy(self.rows[key])

    def save(self, kind: str, data: dict, record_id: str | None = None, version: int | None = None) -> dict:
        key = record_id or f"fixture-{len(self.rows) + 1}"
        current = self.rows.get(key)
        if current is not None and version != current["version"]:
            raise VersionConflict("Fixture version conflict")
        row = {"id": key, "kind": kind, "version": (current["version"] + 1) if current else 1, "data": deepcopy(data)}
        self.rows[key] = row
        return deepcopy(row)


class _Capabilities:
    """Deterministic tool boundary; reports only runtime orchestration behavior."""

    def __init__(self, case: dict) -> None:
        self.case = case
        self.limits = {**DEFAULT_LIMITS, **case.get("limits", {})}
        self.executed: list[str] = []

    async def catalog(self, profile: dict) -> tuple[dict, list]:
        return {name: {"name": name, "read_only": name != "write"} for name in self.case["grants"]}, []

    async def execute(self, spec: dict, arguments: dict, profile: dict, skills: list, approved: bool) -> dict:
        if spec["name"] == "write" and not approved:
            raise DomainError("Fixture write requires approval")
        self.executed.append(spec["name"])
        if spec["name"] == "explode":
            raise ToolError("Fixture upstream unavailable")
        return {"value": "x" * 20000 if spec["name"] == "oversize" else "fixture-result"}


async def evaluate_case(case: dict) -> dict:
    """Run production start/drive/confirm logic with scripted external boundaries."""
    store = _Store()
    capabilities = _Capabilities(case)
    profile = store.save("agent_profile", {"title": "Evaluation", "generate": True, "tool_ids": case["grants"]})
    runtime = AgentRuntime(store, None, capabilities)
    messages = deepcopy(case["messages"])

    async def scripted_model(history: list, specs: dict) -> dict:
        if not messages:
            raise ToolError("Fixture model script exhausted")
        value = messages.pop(0)
        if value == "MODEL_FAILURE":
            raise ToolError("Fixture model unavailable")
        if not isinstance(value, dict):
            raise ToolError("Fixture model response invalid")
        return value

    runtime.model_chat = scripted_model
    started = perf_counter()
    row = await runtime.start(profile["id"], profile["version"], case["task"])
    if "confirm" in case:
        if row["data"]["status"] != "awaiting_confirmation":
            raise EvaluationError("Confirmation fixture did not pause")
        row = await runtime.confirm(row["id"], row["version"], case["confirm"])
    data, expected = row["data"], case["expect"]
    assertions = {"status": data["status"] == expected["status"], "executed": capabilities.executed == expected["executed"]}
    if "answer_contains" in expected:
        assertions["answer_contains"] = expected["answer_contains"] in data["result"]["answer"]
    if "max_calls" in expected:
        assertions["max_calls"] = data["calls_used"] <= expected["max_calls"]
    return {"id": case["id"], "passed": all(assertions.values()), "assertions": assertions,
            "observed": {"status": data["status"], "executed": capabilities.executed,
                         "answer": data["result"]["answer"], "calls_used": data["calls_used"],
                         "model_steps": data["model_steps"], "notes": data["result"]["notes"]},
            "duration_ms": round((perf_counter() - started) * 1000, 3)}


def evaluate_suite(path: Path) -> dict:
    """Return fail-closed contract results bound to exact fixture bytes."""
    suite, digest = load_suite(path)

    async def run() -> list[dict]:
        return [await evaluate_case(case) for case in suite["cases"]]

    cases = anyio.run(run)
    source = Path(__file__).with_name("capability_runtime.py").read_bytes()
    return {"schema": 1, "suite_version": suite["version"], "suite_sha256": digest,
            "runtime_sha256": hashlib.sha256(source).hexdigest(),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "adapter": "scripted-boundaries-real-AgentRuntime", "quality_verified": False,
            "model": "mock", "usage": "unknown", "cost": "unknown",
            "passed": all(c["passed"] for c in cases), "passed_cases": sum(c["passed"] for c in cases),
            "total_cases": len(cases), "cases": cases}
