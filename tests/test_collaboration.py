"""Actual nested AgentRuntime execution with scripted external boundaries, no paid API."""

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.agent.capability_runtime import AgentRuntime
from rag_tech_retriever.agent.collaboration import CollaborationService, validate_plan
from rag_tech_retriever.agent.collaboration_eval import compare
from rag_tech_retriever.agent.evaluation import _Capabilities, _Store
from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigError
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordStore, VersionConflict


def tool(name, arguments, identity):
    return {"content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def done(content="Actual fixture artifact", **extra):
    return {"content": json.dumps({"status": "done", "content": content, **extra})}


class Scripts:
    def __init__(self, values):
        self.values, self.calls = deepcopy(values), []

    def factory(self, actor):
        async def model(messages, specs):
            self.calls.append({"actor": actor, "messages": deepcopy(messages), "specs": deepcopy(specs)})
            assert self.values[actor], "Unexpected additional model request"
            return self.values[actor].pop(0)
        return model


def setup(tmp_path, *, enabled=True, rounds=6, grants=()):
    store = _Store(); caps = _Capabilities({"grants": list(grants)})
    caps.limits["max_steps"] = rounds
    first = store.save("agent_profile", {"title": "Draft worker", "generate": True, "system_prompt": "Draft with evidence"})
    second = store.save("agent_profile", {"title": "Review worker", "generate": True, "system_prompt": "Review, do not invent"})
    supervisor = store.save("agent_profile", {"title": "Retrieval supervisor", "generate": True,
        "handoffs": {"allowed": [first["id"], second["id"]]}})
    plan = [{"step": i, "assignee": row["id"], "input": "Read-only task", "expected": "Cited artifact"}
            for i, row in enumerate([first, second])]
    scripts = Scripts({supervisor["id"]: [tool("propose_plan", {"plan": plan}, "plan"),
        tool("call_worker", {"step": 0}, "dispatch0"), tool("call_worker", {"step": 1}, "dispatch1"),
        {"content": "Summary of actual worker artifacts"}], first["id"]: [done("First artifact")],
        second["id"]: [done("Second artifact")]})
    service = CollaborationService(tmp_path, store, None, caps, scripts.factory)
    service.config["enabled"] = enabled
    return service, supervisor, first, second, plan, scripts


def test_confirmed_plan_real_workers_blackboard_and_chain_budget(tmp_path):
    service, owner, first, second, _, scripts = setup(tmp_path)
    pending = anyio.run(service.start, owner["id"], 1, "Compare evidence")
    assert pending["kind"] == "agent_session" and pending["data"]["kind"] == "collaboration"
    assert pending["data"]["status"] == "awaiting_confirmation" and len(scripts.calls) == 1
    result = anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert result["data"]["status"] == "completed", result["data"]["result"]
    state = result["data"]["shared_state"]
    assert state["phase"] == "done" and [x["content"] for x in state["board"]] == ["First artifact", "Second artifact"]
    assert state["budget"]["model_used"] == 6 and state["budget"]["tool_used"] == 3
    assert {call["actor"] for call in scripts.calls} == {owner["id"], first["id"], second["id"]}
    for entry in state["board"]:
        child = service.store.get(entry["child_id"])
        assert child["kind"] == "agent_session" and child["data"]["parent_collaboration"] == result["id"]
        assert child["data"]["agent"]["id"] == entry["assignee"]


def test_rejected_plan_never_dispatches_and_stale_confirmation_never_repeats(tmp_path):
    service, owner, _, _, _, scripts = setup(tmp_path)
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    denied = anyio.run(service.confirm, pending["id"], pending["version"], False)
    assert denied["data"]["status"] == "failed" and len(scripts.calls) == 1
    with pytest.raises(VersionConflict): anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert len(scripts.calls) == 1


def test_disabled_manual_preview_and_confirmation_cost_nothing_then_explicit_execution(tmp_path):
    service, owner, _, _, plan, scripts = setup(tmp_path, enabled=False)
    pending = anyio.run(service.start, owner["id"], 1, "Manual task", plan)
    approved = anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert approved["data"]["status"] == "confirmed" and scripts.calls == []
    with pytest.raises(DomainError): anyio.run(service.execute, approved["id"], approved["version"])
    service.config["enabled"] = True
    scripts.values[owner["id"]].pop(0)  # Human plan replaces the planning model request, not a dispatch.
    result = anyio.run(service.execute, approved["id"], approved["version"])
    assert result["data"]["status"] == "completed", result["data"]["result"]
    assert result["data"]["shared_state"]["budget"]["model_used"] == 5
    with pytest.raises(VersionConflict): anyio.run(service.execute, approved["id"], approved["version"])


@pytest.mark.parametrize("mutation", ["extra_grant", "wrong_assignee", "bad_number", "bool_number", "empty"])
def test_plan_schema_and_allowlist_are_enforced(mutation):
    plan = [{"step": 0, "assignee": "worker", "input": "Task", "expected": "Artifact"}]
    if mutation == "extra_grant": plan[0]["tool_ids"] = ["admin"]
    if mutation == "wrong_assignee": plan[0]["assignee"] = "outside"
    if mutation == "bad_number": plan[0]["step"] = 2
    if mutation == "bool_number": plan[0]["step"] = False
    if mutation == "empty": plan = []
    with pytest.raises(DomainError): validate_plan(plan, {"worker": {"version": 1}}, 6)


def test_shared_budget_stops_chain_and_never_pretends_completion(tmp_path):
    service, owner, _, second, _, scripts = setup(tmp_path, rounds=3)
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    result = anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert result["data"]["status"] == "fallback"
    assert result["data"]["shared_state"]["budget"]["model_used"] == 3
    assert not any(call["actor"] == second["id"] for call in scripts.calls)
    assert "First artifact" in result["data"]["result"]["answer"]


def test_child_write_approval_is_separate_and_duplicate_cannot_replay(tmp_path):
    service, owner, first, _, plan, scripts = setup(tmp_path, grants=["write"])
    scripts.values[owner["id"]] = [tool("propose_plan", {"plan": plan[:1]}, "plan"),
        tool("call_worker", {"step": 0}, "dispatch0"), {"content": "Done after actual write"}]
    scripts.values[first["id"]] = [tool("write", {}, "actual-write"), done("Wrote with approval")]
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    paused = anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert paused["data"]["status"] == "awaiting_confirmation"
    child = service.store.get(paused["data"]["shared_state"]["pending_child"])
    assert service.capabilities.executed == []
    ordinary = AgentRuntime(service.store, None, service.capabilities)
    with pytest.raises(VersionConflict): anyio.run(ordinary.confirm, child["id"], child["version"], True)
    before = service.get(paused["id"])
    with pytest.raises(VersionConflict):
        anyio.run(service.confirm_child, paused["id"], paused["version"], child["version"] - 1, True)
    assert service.get(paused["id"])["version"] == before["version"]
    done_run = anyio.run(service.confirm_child, paused["id"], paused["version"], child["version"], True)
    assert done_run["data"]["status"] == "completed", done_run["data"]["result"]
    assert service.capabilities.executed == ["write"]
    with pytest.raises(VersionConflict):
        anyio.run(service.confirm_child, paused["id"], paused["version"], child["version"], True)
    assert service.capabilities.executed == ["write"]


@pytest.mark.parametrize("outcome", ["malformed", "need_input", "outside_handoff", "false_completion"])
def test_bad_worker_or_unexecuted_plan_never_becomes_success(tmp_path, outcome):
    service, owner, first, _, _, scripts = setup(tmp_path)
    if outcome == "malformed": scripts.values[first["id"]] = [{"content": "not structured"}]
    if outcome == "need_input": scripts.values[first["id"]] = [{"content": json.dumps({"status": "need_input", "content": "Missing evidence"})}]
    if outcome == "outside_handoff": scripts.values[first["id"]] = [{"content": json.dumps({"status": "handoff_to", "content": "Handoff", "handoff_to": "outside"})}]
    if outcome == "false_completion": scripts.values[owner["id"]] = [{"content": "All workers completed without being called"}]
    run = anyio.run(service.start, owner["id"], 1, "Task")
    if run["data"]["status"] == "awaiting_confirmation":
        run = anyio.run(service.confirm, run["id"], run["version"], True)
    assert run["data"]["status"] == "fallback"
    assert run["data"]["shared_state"]["phase"] != "done"


def test_changed_worker_cannot_be_dispatched_under_old_plan(tmp_path):
    service, owner, first, _, _, scripts = setup(tmp_path)
    run = anyio.run(service.start, owner["id"], 1, "Task")
    service.store.save("agent_profile", {**first["data"], "system_prompt": "Changed"}, first["id"], 1)
    result = anyio.run(service.confirm, run["id"], run["version"], True)
    assert result["data"]["status"] == "fallback" and len(scripts.calls) == 1


def test_authorized_handoff_only_follows_frozen_next_step(tmp_path):
    service, owner, first, second, _, scripts = setup(tmp_path)
    service.store.save("agent_profile", {**first["data"], "handoffs": {"allowed": [second["id"]]}}, first["id"], 1)
    scripts.values[first["id"]] = [{"content": json.dumps({"status": "handoff_to", "content": "Actual first artifact", "handoff_to": second["id"]})}]
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    result = anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert result["data"]["status"] == "completed"
    assert [entry["status"] for entry in result["data"]["shared_state"]["board"]] == ["handoff_to", "done"]


def test_selected_worker_budget_tightens_chain_before_dispatch(tmp_path):
    service, owner, first, _, plan, scripts = setup(tmp_path)
    service.store.save("agent_profile", {**first["data"], "budget": {"max_rounds": 1}}, first["id"], 1)
    scripts.values[owner["id"]] = [tool("propose_plan", {"plan": plan[:1]}, "plan")]
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    result = anyio.run(service.confirm, pending["id"], pending["version"], True)
    state = result["data"]["shared_state"]
    assert state["budget"]["model_limit"] == 1 and state["budget"]["model_used"] == 1
    assert result["data"]["status"] == "fallback" and len(scripts.calls) == 1 and not state["board"]


def test_abort_prevents_old_confirmation_without_replaying_models(tmp_path):
    service, owner, _, _, _, scripts = setup(tmp_path)
    pending = anyio.run(service.start, owner["id"], 1, "Task")
    with pytest.raises(DomainError): service.abort(pending["id"], pending["version"], "skip verification")
    stopped = service.abort(pending["id"], pending["version"], "已核对在途请求，终止协作且不重试")
    assert stopped["data"]["status"] == "failed" and stopped["data"]["shared_state"]["phase"] == "aborted"
    with pytest.raises(VersionConflict): anyio.run(service.confirm, pending["id"], pending["version"], True)
    assert len(scripts.calls) == 1


def test_three_mode_comparison_keeps_original_guards_and_unknowns():
    root = Path(__file__).resolve().parents[1]
    report = compare(root / "data/processed/collaboration_tasks.json", root / "data/processed/agent_golden_set.json")
    assert report["passed"] and len(report["cases"]) == 10 and len(report["r0_compatibility"]) == 30
    assert sum(item["common_comparison"] for item in report["r0_compatibility"]) == 3
    assert not report["quality_verified"] and not report["real_provider_used"] and not report["human_edits_measured"]
    for case in report["cases"]:
        assert len({mode["input_sha256"] for mode in case["modes"]}) == 1
        assert [mode["model_boundary_calls"] for mode in case["modes"]] == [1, 2, 6]
        assert all(mode["cost"] == "unknown" and mode["human_edits"] is None for mode in case["modes"])


@pytest.mark.parametrize("config", ["enabled: false\nenabled: true\n", "[true, false]"])
def test_ambiguous_config_cannot_enable_collaboration(tmp_path, config):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/collaboration.yaml").write_text(config, encoding="utf-8")
    with pytest.raises(ConfigError): CollaborationService(tmp_path, _Store(), None, _Capabilities({}))


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_collab_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client: yield client, store
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}"); cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def create_api_profiles(client):
    workers = [client.post('/api/agents', json={"data": {"title": title, "generate": True}}).json()
               for title in ("Draft", "Review")]
    owner = client.post('/api/agents', json={"data": {"title": "Supervisor", "generate": True,
        "handoffs": {"allowed": [row["id"] for row in workers]}}}).json()
    plan = [{"step": i, "assignee": worker["id"], "input": "Synthetic private plan", "expected": "Artifact"}
            for i, worker in enumerate(workers)]
    return owner, workers, plan


def test_api_manual_plan_confirmation_is_private_idempotent_and_disabled_by_default(api):
    client, store = api; owner, _workers, plan = create_api_profiles(client)
    assert client.get('/api/collaborations/status').json()["enabled"] is False
    bad = client.post('/api/collaborations', json={"agent_id": owner["id"], "version": 1,
        "query": "Synthetic private plan", "plan": plan, "confirmation": ""})
    assert bad.status_code == 400
    response = client.post('/api/collaborations', json={"agent_id": owner["id"], "version": 1,
        "query": "Synthetic private plan", "plan": plan, "confirmation": "仅创建人工计划"})
    assert response.status_code == 201, response.text
    pending = response.json(); assert pending["data"]["status"] == "awaiting_confirmation"
    assert pending["data"]["shared_state"]["budget"]["model_used"] == 0
    path = f'/api/collaborations/{pending["id"]}/confirm'
    body = {"version": pending["version"], "approve": True, "confirmation": "批准计划，不批准Worker写操作"}
    approved = client.post(path, json=body); assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "confirmed"
    assert client.post(path, json=body).status_code == 409
    assert client.post(f'/api/collaborations/{pending["id"]}/execute', json={
        "version": approved.json()["version"], "confirmation": "执行协作计划（可能计费）"}).status_code == 400
    assert pending["id"] not in json.dumps(store.export())
    assert client.get(f'/api/agent-runs/{pending["id"]}').status_code == 404
    assert client.delete(f'/api/records/{pending["id"]}?version={approved.json()["version"]}').status_code == 409
    assert client.post('/api/collaborations', json={"agent_id": owner["id"], "version": 1,
        "query": "Q", "plan": plan, "confirmation": "仅创建人工计划", "model_script": []}).status_code == 400


def test_api_real_versioned_children_persist_and_duplicate_dispatch_is_rejected(api):
    client, store = api; owner, workers, plan = create_api_profiles(client)
    service = client.app.state.collaboration_service
    service.config["enabled"] = True
    scripts = Scripts({owner["id"]: [tool("propose_plan", {"plan": plan}, "plan"),
        tool("call_worker", {"step": 0}, "one"), tool("call_worker", {"step": 1}, "two"), {"content": "Summary"}],
        workers[0]["id"]: [done("First actual child")], workers[1]["id"]: [done("Second actual child")]})
    service.model_factory = scripts.factory
    pending = client.post('/api/collaborations', json={"agent_id": owner["id"], "version": 1,
        "query": "Task", "confirmation": "生成协作计划（可能计费）"}).json()
    path = f'/api/collaborations/{pending["id"]}/confirm'
    body = {"version": pending["version"], "approve": True, "confirmation": "批准计划，不批准Worker写操作"}
    response = client.post(path, json=body); assert response.status_code == 200, response.text
    result = response.json(); assert result["data"]["status"] == "completed"
    assert client.post(path, json=body).status_code == 409
    children = [store.get(row["child_id"]) for row in result["data"]["shared_state"]["board"]]
    assert len(children) == 2 and all(row["data"]["parent_collaboration"] == result["id"] for row in children)
    assert client.post(f'/api/agent-runs/{children[0]["id"]}/continue', json={"version": children[0]["version"], "query": "Bypass"}).status_code == 409
    exported = json.dumps(store.export())
    assert result["id"] not in exported and all(child["id"] not in exported for child in children)
