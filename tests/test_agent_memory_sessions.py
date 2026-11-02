"""Confirm-first private memory and CAS session lifetime; no paid providers."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.agent.capability_runtime import _MODEL_OPTIONS, AgentRuntime
from rag_tech_retriever.agent.evaluation import _Capabilities, _Store
from rag_tech_retriever.agent.memory import validate_memory
from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.snapshot import validate_snapshot
from rag_tech_retriever.platform.record_store import RecordStore, VersionConflict


@pytest.mark.parametrize("value", [None, True, "", "   ", "a" * 2001])
def test_memory_plain_text_is_bounded(value):
    with pytest.raises(DomainError): validate_memory(value, 2000)


def test_scope_defaults_and_invalid_scope():
    assert validate_agent({"title": "Legacy"})["memory"] == {"scope": "none"}
    with pytest.raises(DomainError): validate_agent({"title": "Bad", "memory": {"scope": "auto"}})


def test_actual_model_cancellation_keeps_failed_span_and_resets_scoped_options():
    store = _Store(); caps = _Capabilities({"grants": []})
    caps.limits["run_timeout_seconds"] = 1
    profile = store.save("agent_profile", {"title": "Timeout", "generate": True})
    runtime = AgentRuntime(store, None, caps)

    async def slow(*args): await anyio.sleep(2)

    runtime.model_chat = slow
    result = anyio.run(runtime.start, profile["id"], 1, "Task")["data"]
    assert result["status"] == "failed" and "超时" in result["result"]["notes"][0]
    event = result["trace"][-1]
    assert event["status"] == "failed" and event["duration_ms"] >= 900
    assert event["usage"]["total_tokens"] is None and _MODEL_OPTIONS.get() is None


def test_session_uses_server_history_and_cumulative_budget_not_replayable_client_history():
    store = _Store(); caps = _Capabilities({"grants": []})
    agent = store.save("agent_profile", {"title": "Session", "generate": True,
        "memory": {"scope": "session"}, "budget": {"max_rounds": 2}})
    runtime = AgentRuntime(store, None, caps); observed = []

    async def model(messages, specs):
        observed.append(deepcopy(messages)); return {"content": "answer " + str(len(observed))}

    runtime.model_chat = model
    first = anyio.run(runtime.start, agent["id"], 1, "constraint one")
    second = anyio.run(runtime.continue_run, first["id"], first["version"], "question two")
    assert second["kind"] == "agent_session" and second["data"]["turns"] == 2
    assert [m["content"] for m in observed[-1] if m["role"] != "system"] == ["constraint one", "answer 1", "question two"]
    with pytest.raises(VersionConflict):
        anyio.run(runtime.continue_run, first["id"], first["version"], "duplicate")
    third = anyio.run(runtime.continue_run, second["id"], second["version"], "over budget")
    assert third["data"]["status"] == "failed" and len(observed) == 2
    with pytest.raises(VersionConflict):
        anyio.run(runtime.continue_run, third["id"], third["version"], "retry failure")


def test_default_none_cannot_reuse_run_and_changed_profile_cannot_continue():
    store = _Store(); caps = _Capabilities({"grants": []})
    agent = store.save("agent_profile", {"title": "No implicit memory", "generate": True})
    runtime = AgentRuntime(store, None, caps)

    async def model(*args): return {"content": "answer"}

    runtime.model_chat = model
    result = anyio.run(runtime.start, agent["id"], 1, "Task")
    with pytest.raises(VersionConflict): anyio.run(runtime.continue_run, result["id"], result["version"], "No")

    agent = store.save("agent_profile", {**agent["data"], "memory": {"scope": "session"}}, agent["id"], 1)
    result = anyio.run(runtime.start, agent["id"], 2, "Task")
    store.save("agent_profile", {**agent["data"], "title": "New"}, agent["id"], 2)
    with pytest.raises(VersionConflict): anyio.run(runtime.continue_run, result["id"], result["version"], "No")


def test_closed_session_cannot_resume_or_close_twice():
    store = _Store(); caps = _Capabilities({"grants": []})
    agent = store.save("agent_profile", {"title": "Close", "generate": True, "memory": {"scope": "session"}})
    runtime = AgentRuntime(store, None, caps)

    async def model(*args): return {"content": "answer"}

    runtime.model_chat = model
    run = anyio.run(runtime.start, agent["id"], 1, "First")
    closed = runtime.close_run(run["id"], run["version"])
    assert closed["data"]["closed"]
    with pytest.raises(VersionConflict): runtime.close_run(closed["id"], closed["version"])
    with pytest.raises(VersionConflict): anyio.run(runtime.continue_run, closed["id"], closed["version"], "No")


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_memory_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client: yield client, store
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def agent(client, scope="persistent"):
    r = client.post("/api/agents", json={"data": {"title": "QA memory", "generate": True,
        "memory": {"scope": scope}}}); assert r.status_code == 201; return r.json()


def proposal(client, owner, content="Synthetic private preference", request_id=None):
    r = client.post(f'/api/agents/{owner["id"]}/memory', json={"agent_version": owner["version"],
        "content": content, "request_id": request_id or uuid4().hex})
    assert r.status_code == 201, r.text; return r.json()


def decide(client, owner, item, action="confirm", confirmation=None):
    words = {"confirm": "确认保存长期记忆", "reject": "拒绝记忆", "forget": "确认遗忘"}
    return client.post(f'/api/agents/{owner["id"]}/memory/{item["id"]}/decide', json={
        "agent_version": owner["version"], "version": item["version"], "action": action,
        "confirmation": words[action] if confirmation is None else confirmation})


def test_memory_confirmation_rejection_forgetting_idempotence_and_owner_isolation(api):
    client, store = api; owner = agent(client); other = agent(client)
    pending = proposal(client, owner, request_id="stable")
    again = proposal(client, owner, request_id="stable")
    assert again["id"] == pending["id"] and again["version"] == pending["version"]
    assert pending["data"]["state"] == "pending"
    assert decide(client, owner, pending, confirmation="").status_code == 400
    assert decide(client, other, pending).status_code == 404
    confirmed = decide(client, owner, pending); assert confirmed.status_code == 200
    assert decide(client, owner, pending).status_code == 409
    forgotten = decide(client, owner, confirmed.json(), "forget"); assert forgotten.status_code == 200
    assert forgotten.json()["data"]["state"] == "forgotten"
    assert client.post(f'/api/records/{pending["id"]}/restore', json={"target_version": 2,
        "current_version": 3}).status_code == 409
    assert client.delete(f'/api/records/{pending["id"]}?version=3').status_code == 409
    rejected = proposal(client, owner, "Reject me")
    assert decide(client, owner, rejected, "reject").json()["data"]["state"] == "rejected"
    assert decide(client, owner, store.get(rejected["id"])).status_code == 409


def test_memory_cannot_confirm_after_grant_change_and_concurrent_confirm_is_once(api):
    client, _ = api; owner = agent(client); pending = proposal(client, owner)
    changed = client.put(f'/api/agents/{owner["id"]}', json={"version": 1, "data": {"title": "Changed"}}).json()
    assert decide(client, changed, pending).status_code == 409
    assert decide(client, changed, pending, "reject").status_code == 200
    pending = proposal(client, changed, "New confirmed fact")
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: decide(client, changed, pending).status_code, range(2)))
    assert sorted(statuses) == [200, 409]


def test_only_confirmed_facts_project_private_runs_export_restore_isolation_and_forget_blocks_continuation(api):
    client, store = api; owner = agent(client)
    pending = proposal(client, owner, "PENDING SECRET")
    confirmed = decide(client, owner, proposal(client, owner, "CONFIRMED SECRET")).json()
    runtime = client.app.state.agent_runtime; histories = []

    async def model(messages, specs):
        histories.append(deepcopy(messages)); return {"content": "CONFIRMED SECRET in answer"}

    runtime.model_chat = model
    run = client.post(f'/api/agents/{owner["id"]}/run', json={"version": 1, "query": "Use preferences"}).json()
    assert run["kind"] == "agent_session" and run["data"]["status"] == "completed"
    forged = {**run, "kind": "workflow_run"}
    with pytest.raises(DomainError): validate_snapshot({"format_version": 1, "records": [forged]})
    raw = json.dumps(histories[0]); assert "CONFIRMED SECRET" in raw and "PENDING SECRET" not in raw
    assert "CONFIRMED SECRET" not in json.dumps(run["data"]["messages"][:-1])
    exported = store.export()
    assert "CONFIRMED SECRET" not in json.dumps(exported) and "PENDING SECRET" not in json.dumps(exported)
    assert all(r["kind"] not in {"agent_memory", "agent_session"} for r in exported["records"])
    target = deepcopy(exported); target["records"].append({"id": run["id"], "kind": "knowledge", "data": {}})
    with pytest.raises(VersionConflict): store.restore_snapshot(target)
    store.restore_snapshot(exported)
    assert store.get(run["id"])["kind"] == "agent_session" and store.get(pending["id"])["kind"] == "agent_memory"
    assert decide(client, owner, confirmed, "forget").status_code == 200
    after = client.post(f'/api/agent-runs/{run["id"]}/continue', json={"version": run["version"], "query": "Again"})
    assert after.status_code == 409 and len(histories) == 1
    assert client.get('/api/agent-runs').status_code == 200


def test_session_limits_and_unknown_client_fields_do_not_trigger_extra_provider_calls(api):
    client, _ = api; owner = agent(client, "session"); runtime = client.app.state.agent_runtime
    calls = []

    async def model(messages, specs): calls.append(messages); return {"content": "answer"}

    runtime.model_chat = model
    run = client.post(f'/api/agents/{owner["id"]}/run', json={"version": 1, "query": "First"}).json()
    path = f'/api/agent-runs/{run["id"]}/continue'
    assert client.post(path, json={"version": run["version"], "query": "Second", "messages": []}).status_code == 400
    assert len(calls) == 1
    next_run = client.post(path, json={"version": run["version"], "query": "Second"}); assert next_run.status_code == 200
    assert client.post(path, json={"version": run["version"], "query": "Duplicate"}).status_code == 409
    runtime.capabilities.limits["max_session_turns"] = 2
    assert client.post(path, json={"version": next_run.json()["version"], "query": "Third"}).status_code == 400
    assert len(calls) == 2
    assert client.post(f'/api/records/{run["id"]}/restore', json={"target_version": 1,
        "current_version": next_run.json()["version"]}).status_code == 409


def test_private_kinds_rejected_by_public_snapshot_and_disabled_scope_cannot_write(api):
    client, _ = api; owner = agent(client, "none")
    assert client.post(f'/api/agents/{owner["id"]}/memory', json={"agent_version": 1,
        "content": "No implicit memory", "request_id": "disabled"}).status_code == 400
    for kind in ("agent_memory", "agent_session"):
        with pytest.raises(DomainError):
            validate_snapshot({"format_version": 1, "records": [{"id": "forged", "kind": kind, "data": {}}]})


def test_setup_after_custom_agent_creates_isolated_basic_workflows_without_reusing_memory(api):
    client, store = api; custom = agent(client)
    assert client.get('/api/workflows').json() == []
    assert client.post('/api/automation/setup').json()["created"]
    workflows = client.get('/api/workflows').json()
    assert {row["data"]["kind"] for row in workflows} == {"answer", "ingest"}
    answer = next(row for row in workflows if row["data"]["kind"] == "answer")
    basic = store.get(answer["data"]["agent_id"])
    assert basic["id"] != custom["id"] and basic["data"]["memory"]["scope"] == "none"
    assert store.get(custom["id"])["version"] == custom["version"]
    assert not client.post('/api/automation/setup').json()["created"]
