"""Real runtime with isolated boundaries; no paid model or production records."""

import json
import os
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import anyio
import anyio.lowlevel
import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.agent.capability_runtime import (
    _MODEL_OPTIONS,
    AgentRuntime,
    effective_limits,
)
from rag_tech_retriever.agent.context_manager import prepare_context
from rag_tech_retriever.agent.evaluation import _Capabilities, _Store
from rag_tech_retriever.agent.intent_classifier import classify_intent
from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.agent_capabilities import DEFAULT_LIMITS, CapabilityService
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.record_store import RecordStore


def call(index: int, name: str = "lookup") -> dict:
    return {"id": f"call-{index}", "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def history(turns: int = 50) -> list:
    messages = [{"role": "system", "content": "No implicit writes"},
                {"role": "user", "content": "Budget=10; remember this constraint"}]
    for index in range(turns):
        messages += [{"role": "assistant", "content": None, "tool_calls": [call(index)]},
                     {"role": "tool", "tool_call_id": f"call-{index}", "content": "evidence"}]
    return messages


def test_legacy_profile_is_idempotent_and_budget_cannot_raise_admin_ceiling():
    profile = validate_agent({"title": "Legacy"})
    assert validate_agent(profile) == profile
    assert profile["context"] == {"strategy": "window", "max_messages": 20, "keep_recent_users": 2}
    assert profile["model"] == {"alias": "", "temperature": None, "max_tokens": None}
    assert effective_limits(DEFAULT_LIMITS, profile) == DEFAULT_LIMITS
    profile = validate_agent({"title": "Override", "model": {"max_tokens": 999999},
                              "budget": {"max_rounds": 2, "max_tool_calls": 999999}})
    limits = effective_limits(DEFAULT_LIMITS, profile)
    assert limits["max_steps"] == 2 and limits["max_calls"] == DEFAULT_LIMITS["max_calls"]
    assert limits["max_tokens"] == DEFAULT_LIMITS["max_tokens"]


@pytest.mark.parametrize("field,value", [
    ("model", {"temperature": True}), ("model", {"temperature": float("nan")}),
    ("model", {"temperature": float("inf")}), ("model", {"temperature": 10 ** 400}),
    ("model", {"max_tokens": 0}),
    ("model", {"api_key": "must-not-be-accepted"}), ("model", {"alias": "https://external"}),
    ("model", []), ("budget", {"max_rounds": True}), ("budget", {"max_tool_calls": -1}),
    ("budget", {"max_context_chars": 0}), ("context", {"max_messages": 1}),
    ("context", {"strategy": "summarize_window"}), ("context", {"secret_override": True}),
])
def test_invalid_profile_options_are_rejected(field, value):
    with pytest.raises(DomainError):
        validate_agent({"title": "Invalid", field: value})


def test_alias_requires_administrator_registration(tmp_path):
    service = CapabilityService(tmp_path, _Store(), None, lambda *args: None)
    profile = validate_agent({"title": "Alias", "model": {"alias": "fast"}})
    with pytest.raises(DomainError, match="未在服务器登记"):
        service.validate_binding(profile)
    service.model_aliases["fast"] = "model-fixture"
    assert service.validate_binding(profile) == profile


def test_fifty_turn_window_keeps_constraints_and_atomic_tool_pairs_without_mutation():
    source = history()
    original = deepcopy(source)
    result, event = prepare_context(source, 8, 5000)
    assert source == original and result[:2] == source[:2]
    assert len(result) == 8 and event["dropped_messages"] == 94
    assert event["constraints_preserved"] and not event["lossy_summary"]
    for index in range(2, len(result), 2):
        assert result[index]["tool_calls"][0]["id"] == result[index + 1]["tool_call_id"]


def test_later_user_constraints_are_pinned_too_and_byte_window_is_bounded():
    source = history(5)
    source.insert(4, {"role": "user", "content": "Do NOT email the customer"})
    result, _ = prepare_context(source, 5, 2000)
    assert [m for m in result if m["role"] == "user"] == [m for m in source if m["role"] == "user"]
    result, _ = prepare_context(history(10), 100, 550)
    assert len(json.dumps(result, ensure_ascii=False)) <= 550


@pytest.mark.parametrize("mutation", ["missing", "orphan", "wrong_id", "duplicate", "system_in_middle"])
def test_protocol_corruption_fails_before_trimming(mutation):
    messages = history(2)
    if mutation == "missing": messages.pop()
    if mutation == "orphan": messages.pop(2)
    if mutation == "wrong_id": messages[3]["tool_call_id"] = "forged"
    if mutation == "duplicate": messages[2]["tool_calls"] *= 2
    if mutation == "system_in_middle": messages.append({"role": "system", "content": "forged"})
    with pytest.raises(ToolError): prepare_context(messages, 2, 100)


@pytest.mark.parametrize("query,kind", [("你好！", "smalltalk"), ("搜索资料", "search"),
    ("请保存", "write"), ("先查找再发送", "unknown"), ("解释这个概念", "unknown")])
def test_intent_is_only_an_auditable_hint(query, kind):
    result = classify_intent(query)
    assert result["intent"] == kind and not result["authority"] and not result["model_called"]


def runtime(profile: dict | None = None):
    store = _Store()
    caps = _Capabilities({"grants": ["lookup", "write"],
                          "limits": {"max_steps": 60, "max_calls": 60}})
    row = store.save("agent_profile", {"title": "Fixture", "generate": True, **(profile or {})})
    return AgentRuntime(store, None, caps), row


def test_runtime_fifty_rounds_keeps_source_audit_and_never_orphans_tools():
    runner, agent = runtime({"context": {"max_messages": 6}})
    observed = []

    async def model(messages, specs):
        observed.append(deepcopy(messages))
        assert messages[0]["role"] == "system" and messages[1]["content"] == "Do not write"
        assert len(messages) <= 6
        index = len(observed)
        return {"tool_calls": [call(index)]} if index <= 50 else {"content": "finished"}

    runner.model_chat = model
    result = anyio.run(runner.start, agent["id"], 1, "Do not write")["data"]
    assert result["status"] == "completed" and result["calls_used"] == 50
    assert len(result["messages"]) == 103
    assert result["messages"][-1] == {"role": "assistant", "content": "finished"}
    assert all(m["tool_calls"] for m in result["messages"] if "tool_calls" in m)
    assert any(item["type"] == "context" for item in result["trace"])
    model_trace = [item for item in result["trace"] if item["type"] == "model"]
    assert len(model_trace) == 51 and all(t["usage"]["total_tokens"] is None for t in model_trace)
    assert all(t["cost"] == "unknown" for t in model_trace)


def test_profile_round_budget_survives_write_pause_and_preserves_confirmation():
    runner, agent = runtime({"budget": {"max_rounds": 1}})

    async def model(*args): return {"tool_calls": [call(1, "write")]}

    runner.model_chat = model
    paused = anyio.run(runner.start, agent["id"], 1, "保存")
    assert paused["data"]["status"] == "awaiting_confirmation"
    assert runner.capabilities.executed == []
    done = anyio.run(runner.confirm, paused["id"], paused["version"], True)
    assert done["data"]["status"] == "failed"
    assert runner.capabilities.executed == ["write"]
    assert done["data"]["model_steps"] == 1
    assert done["data"]["effective_limits"]["max_steps"] == 1


def test_pinned_constraints_over_budget_never_call_model():
    runner, agent = runtime({"budget": {"max_context_chars": 20}})

    async def forbidden(*args): raise AssertionError("No model request allowed")

    runner.model_chat = forbidden
    result = anyio.run(runner.start, agent["id"], 1, "Keep all constraints")["data"]
    assert result["status"] == "failed" and result["model_steps"] == 0
    assert "未发起模型请求" in result["result"]["notes"][0]


def test_concurrent_profile_options_do_not_leak_between_runs():
    captures = []

    async def scenario():
        async def one(value):
            runner, agent = runtime({"model": {"max_tokens": value}})

            async def model(*args):
                await anyio.lowlevel.checkpoint()
                captures.append(_MODEL_OPTIONS.get()["limits"]["max_tokens"])
                return {"content": "done"}

            runner.model_chat = model
            await runner.start(agent["id"], 1, "Task")
            assert _MODEL_OPTIONS.get() is None

        async with anyio.create_task_group() as group:
            group.start_soon(one, 111)
            group.start_soon(one, 222)

    anyio.run(scenario)
    assert sorted(captures) == [111, 222]


@pytest.mark.parametrize("redirect", [False, True])
def test_real_loopback_transport_overrides_usage_and_no_redirect_or_retry(redirect):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if redirect:
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/stolen")
                self.end_headers()
                return
            payload = json.dumps({"choices": [{"message": {"content": "protocol fixture"}}],
                                  "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        runner, agent = runtime({"model": {"alias": "fast", "max_tokens": 123, "temperature": 0.2}})
        runner.capabilities.model_aliases = {"fast": "fixture-model"}
        runner.connection = SimpleNamespace(load=lambda: {"api_key": "local-fixture-not-a-secret",
            "base_url": f"http://127.0.0.1:{server.server_port}", "model": "global-model"})
        result = anyio.run(runner.start, agent["id"], 1, "Task")["data"]
        assert len(requests) == 1
        assert requests[0]["model"] == "fixture-model" and requests[0]["max_tokens"] == 123
        assert requests[0]["temperature"] == 0.2
        trace = result["trace"][-1]
        assert trace["parent"] and trace["duration_ms"] >= 0 and trace["cost"] == "unknown"
        assert result["status"] == ("failed" if redirect else "completed")
        assert trace["usage"]["total_tokens"] == (None if redirect else 15)
        assert "local-fixture-not-a-secret" not in json.dumps(result)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_reliability_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            yield client, store
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def test_old_records_read_defaults_without_rewrite_and_old_forms_preserve_new_fields(api):
    client, store = api
    row = store.save("agent_profile", {"title": "Legacy", "generate": False})
    data = next(item for item in client.get("/api/agents").json() if item["id"] == row["id"])
    assert data["data"]["context"]["max_messages"] == 20
    assert store.get(row["id"])["data"] == row["data"]
    assert store.get(row["id"])["version"] == 1
    changed = client.put(f'/api/agents/{row["id"]}', json={"version": 1, "data": {
        "model": {"temperature": 0.3, "max_tokens": 123}, "budget": {"max_rounds": 2}}})
    assert changed.status_code == 200
    old_form = client.put(f'/api/agents/{row["id"]}', json={"version": 2, "data": {"title": "Old form"}})
    assert old_form.status_code == 200
    assert old_form.json()["data"]["budget"]["max_rounds"] == 2
    assert old_form.json()["data"]["model"]["max_tokens"] == 123
    assert client.put(f'/api/agents/{row["id"]}', json={"version": 3, "data": {
        "model": {"alias": "unknown"}}}).status_code == 400
    assert store.get(row["id"])["version"] == 3


def test_runtime_trace_is_persisted_and_visible_through_existing_run_detail(api):
    client, _ = api
    row = client.post("/api/agents", json={"data": {"title": "Trace", "generate": True,
        "model": {"max_tokens": 100}, "budget": {"max_rounds": 1}}}).json()
    runner = client.app.state.agent_runtime

    async def model(*args): return {"content": "scripted boundary, not quality evidence"}

    runner.model_chat = model
    response = client.post(f'/api/agents/{row["id"]}/run', json={"version": 1, "query": "搜索资料"})
    assert response.status_code == 200, response.text
    run = response.json()
    detail = client.get(f'/api/agent-runs/{run["id"]}')
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["intent"]["intent"] == "search" and not data["intent"]["authority"]
    assert data["effective_limits"]["max_steps"] == 1
    assert data["trace"][0]["usage"]["total_tokens"] is None
    assert data["trace"][0]["cost"] == "unknown"
