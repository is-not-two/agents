"""Workflow policy validation rejects malformed JSON without writing records."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from rag_tech_retriever.api.routes.automation import create_router
from rag_tech_retriever.common.middleware.exception import AppError
from rag_tech_retriever.domains.automation import validate_workflow
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.workflow_graph import validate_graph_workflow
from rag_tech_retriever.platform.record_store import VersionConflict


def policy_graph(field=None, value=None):
    data = {
        "title": "isolated policy fixture", "kind": "graph",
        "nodes": [{"id": "input", "type": "input"}, {"id": "end", "type": "merge"}],
        "edges": [["input", "end"]],
    }
    if field == "join_policy":
        data[field] = value
    elif field == "retry_on":
        data["nodes"][1]["retry"] = {field: [value]}
    elif field:
        data["nodes"][1][field] = value
    return data


@pytest.mark.parametrize("field", ["on_error", "retry_on", "join_policy"])
@pytest.mark.parametrize("value", [[], {}, None, True, 1, "", "unsupported"])
def test_malformed_policy_is_a_domain_error(field, value):
    data = policy_graph(field, value)
    original = deepcopy(data)
    for validate in (validate_graph_workflow, validate_workflow):
        with pytest.raises(DomainError):
            validate(data)
        assert data == original


def test_valid_policies_and_defaults_are_preserved():
    defaults = validate_graph_workflow(policy_graph())
    assert defaults["join_policy"] == "all_success"
    assert defaults["nodes"][1]["on_error"] == "fail"
    for value in ("all_success", "any_success"):
        assert validate_graph_workflow(policy_graph("join_policy", value))["join_policy"] == value
    for value in ("fail", "continue", "fallback"):
        data = policy_graph("on_error", value)
        if value == "fallback":
            data["nodes"][1]["fallback"] = {"answer": "isolated fallback"}
        assert validate_graph_workflow(data)["nodes"][1]["on_error"] == value
    for value in ("timeout", "tool_error"):
        data = validate_graph_workflow(policy_graph("retry_on", value))
        assert data["nodes"][1]["retry"]["retry_on"] == [value]


class MemoryStore:
    """Isolated records only; no configuration, personal data or database access."""

    def __init__(self):
        self.rows = {}

    def get(self, record_id):
        return deepcopy(self.rows[record_id])

    def save(self, kind, data, record_id=None, version=None):
        if record_id is not None and self.rows[record_id]["version"] != version:
            raise VersionConflict("stale fixture")
        record_id = record_id or f"fixture-{len(self.rows) + 1}"
        self.rows[record_id] = {
            "id": record_id, "kind": kind,
            "version": self.rows.get(record_id, {}).get("version", 0) + 1,
            "data": deepcopy(data),
        }
        return self.get(record_id)


def isolated_client():
    store = MemoryStore()
    app = FastAPI()

    @app.exception_handler(AppError)
    async def domain_error(request, exc):
        return JSONResponse(exc.payload(), status_code=exc.http_status)

    @app.exception_handler(VersionConflict)
    async def version_conflict(request, exc):
        return JSONResponse({"code": "VERSION_CONFLICT"}, status_code=409)

    app.include_router(create_router(SimpleNamespace(
        store=store, search=None, capabilities=None, runtime=None,
    )))
    return TestClient(app, raise_server_exceptions=False), store


@pytest.mark.parametrize("field", ["on_error", "retry_on", "join_policy"])
@pytest.mark.parametrize("value", [[], {}])
def test_policy_create_and_update_return_400_without_writes(field, value):
    client, store = isolated_client()
    with client:
        invalid = policy_graph(field, value)
        response = client.post("/api/workflows", json={"data": invalid})
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert store.rows == {}
        created = client.post("/api/workflows", json={"data": policy_graph()})
        assert created.status_code == 201
        row = created.json()
        before = deepcopy(store.rows)
        response = client.put(f"/api/workflows/{row['id']}", json={
            "data": invalid, "version": row["version"],
        })
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert store.rows == before


def test_existing_approval_chain_still_runs_and_rejects_stale_confirmation():
    client, store = isolated_client()
    data = policy_graph()
    data["nodes"].insert(1, {"id": "gate", "type": "approval", "message": "fixture approval"})
    data["edges"] = [["input", "gate"], ["gate", "end"]]
    with client:
        created = client.post("/api/workflows", json={"data": data})
        assert created.status_code == 201
        workflow = created.json()
        run = client.post(f"/api/workflows/{workflow['id']}/run", json={
            "version": workflow["version"], "input": {"query": "isolated fixture"},
        })
        assert run.status_code == 200
        paused = run.json()
        assert paused["data"]["status"] == "awaiting_confirmation"
        path = f"/api/workflow-runs/{paused['id']}/confirm"
        confirmation = {"version": paused["version"], "approve": True}
        finished = client.post(path, json=confirmation)
        assert finished.status_code == 200
        assert finished.json()["data"]["status"] == "completed"
        assert finished.json()["data"]["node_status"] == {
            "input": "completed", "gate": "completed", "end": "completed",
        }
        before = deepcopy(store.rows)
        assert client.post(path, json=confirmation).status_code == 409
        assert store.rows == before
