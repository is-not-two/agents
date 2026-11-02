"""Opt-in readonly MCP queries, real PostgreSQL and credential scope counterexamples."""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.api.routes import mcp as mcp_routes
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.learning import validate_card
from rag_tech_retriever.domains.life_planning import DomainError, validate_plan
from rag_tech_retriever.platform.jobs import JobsService
from rag_tech_retriever.platform.mcp_policy import BUSINESS_TOOLS, query_limits, validate_mcp_config
from rag_tech_retriever.platform.mcp_queries import BusinessQueries
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.operations import configuration_report
from rag_tech_retriever.platform.record_store import RecordStore, StorageError
from rag_tech_retriever.platform.weekly_report import WeeklyReport

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def config(tmp_path, enabled=True, **extra):
    value = {"tools": {name: {"enabled": enabled, "permission": "readonly"} for name in BUSINESS_TOOLS | {"knowledge_search"}},
             "permissions": {"readonly": True, "admin": False}, "resources": {"corpus": {"enabled": False}}, **extra}
    path = tmp_path / (uuid4().hex + ".yaml"); path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return ConfigLoader(path)


@pytest.mark.parametrize("bad", [{"max_limit": True}, {"max_limit": 0}, {"max_limit": 10**400}, {"max_limit": "50"}, {"default_limit": 60}, {"unknown": 1}])
def test_query_policy_rejects_coercion_and_overflow(bad):
    with pytest.raises(DomainError): query_limits(bad)


@pytest.mark.parametrize("value", [{"permissions": {"admin": True}}, {"tools": {"delete_all": {"enabled": True}}},
                                    {"tools": {"jobs_search": {"enabled": "false"}}}, {"tools": {"jobs_search": {"enabled": True, "permission": "admin"}}}])
def test_mcp_policy_cannot_widen_to_writes(tmp_path, value):
    with pytest.raises(DomainError): validate_mcp_config(config(tmp_path, **value))


def test_default_catalog_excludes_business_and_disabled_readonly_exposes_nothing(tmp_path):
    default = ConfigLoader(ROOT / "config/mcp.yaml")
    server = mcp_routes.build_mcp_server(object(), default)
    names = {x.name for x in asyncio.run(server.list_tools())}
    assert not names & BUSINESS_TOOLS and {"search_docs", "knowledge_search"} <= names
    disabled = config(tmp_path, permissions={"readonly": False, "admin": False}, resources={"corpus": {"enabled": True}})
    server = mcp_routes.build_mcp_server(object(), disabled)
    assert not asyncio.run(server.list_tools()) and not asyncio.run(server.list_resources())


@pytest.fixture
def store(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    value = RecordStore("qa_mcpbiz_" + uuid4().hex[:8]); value.ensure_schema()
    try: yield value
    finally:
        with value.transaction() as cur:
            cur.execute(f"DROP TABLE {value.versions}"); cur.execute(f"DROP TABLE {value.records}")


def snapshot(store):
    with store.transaction() as cur:
        cur.execute(f"SELECT * FROM {store.records} ORDER BY id"); rows = cur.fetchall()
        cur.execute(f"SELECT * FROM {store.versions} ORDER BY record_id,version"); versions = cur.fetchall()
    return hashlib.sha256(json.dumps([rows, versions], default=str, sort_keys=True).encode()).hexdigest()


def seed(store):
    jobs = JobsService(store)
    leads, apps = [], []
    for i, company in enumerate(["Acme%_", "Acme Plain", "Other"]):
        lead = jobs.save("job_lead", {"title": "Python Backend", "company": company, "jd_text": "HIDDEN_JD", "notes": "HIDDEN_LEAD_NOTE"})
        app = jobs.save("application", {"lead_id": lead["id"], "status": "applied", "applied_at": "2026-10-27T00:00:00Z", "follow_up_at": "2026-10-28T00:00:00Z", "notes": "HIDDEN_APPLICATION_NOTE"})
        leads.append(lead); apps.append(app)
    for title, due, paused in [("due card", "2026-10-28T00:00:00Z", False), ("exact boundary", NOW.isoformat(), False),
                               ("future card", "2027-01-01T00:00:00Z", False), ("paused card", "2026-10-28T00:00:00Z", True)]:
        store.save("learning_card", validate_card({"title": title, "due_at": due, "paused": paused, "answer_ref": "HIDDEN_ANSWER"}))
    return jobs, leads, apps


def query_service(store, tmp_path, **limits):
    return BusinessQueries(store, tmp_path, ModelConnection(tmp_path / "never-load.json"), limits or None, lambda: NOW)


def test_real_queries_are_bounded_literal_projected_and_no_writes(store, tmp_path):
    jobs, _leads, apps = seed(store); service = query_service(store, tmp_path)
    before = snapshot(store)
    result = service.jobs_search(company="%_", position="backend", status="applied", limit=1)
    assert [row["id"] for row in result["applications"]] == [apps[0]["id"]]
    assert result["applications"][0]["follow_up_due"] is True and not result["has_more"]
    assert not service.jobs_search(company="' OR 1=1 --")["applications"]
    first = service.jobs_search(limit=1); second = service.jobs_search(limit=1, offset=first["next_offset"])
    assert first["has_more"] and first["applications"][0]["id"] != second["applications"][0]["id"]
    cards = service.learning_due()
    assert {row["title"] for row in cards["cards"]} == {"due card", "exact boundary"}
    assert all(type(row["repetitions"]) is int for row in cards["cards"])
    assert "HIDDEN_" not in json.dumps([result, first, second, cards])
    assert snapshot(store) == before
    # PostgreSQL enforces the readonly transaction, not just tool annotations.
    with pytest.raises(StorageError), service._read() as cur:
        cur.execute(f"DELETE FROM {store.records}")
    assert snapshot(store) == before
    jobs.archive(apps[0]["id"], apps[0]["version"])
    assert not service.jobs_search(company="%_")["applications"]


def test_weekly_uses_same_statistics_and_refuses_truncated_numbers(store, tmp_path, monkeypatch):
    seed(store); service = query_service(store, tmp_path)
    monkeypatch.setattr(ModelConnection, "load", lambda self: (_ for _ in ()).throw(AssertionError("No provider settings may be loaded")))
    before = snapshot(store)
    expected = WeeklyReport(tmp_path, store, service.connection).report("2026-10-29", now=NOW)
    actual = service.jobs_weekly_stats("2026-10-29")
    assert actual["metrics"] == expected["metrics"] and actual["mode"] == "statistics"
    assert actual["metrics"]["applications_submitted"] == 3
    assert not {"top_questions", "top_weak_points", "answer", "focus_keys"} & actual.keys()
    assert snapshot(store) == before and not (tmp_path / "data").exists()
    with pytest.raises(DomainError, match="截断"):
        query_service(store, tmp_path, max_stats_records=1).jobs_weekly_stats("2026-10-29")
    assert snapshot(store) == before
    for day in ("not-date", "2026-02-30", "9999-12-31", "0001-01-01"):
        with pytest.raises(DomainError): service.jobs_weekly_stats(day)


def test_empty_rate_and_visible_title_pagination_limits(store, tmp_path):
    service = query_service(store, tmp_path, max_title_chars=12, max_offset=1, default_limit=1, max_limit=1)
    assert service.jobs_weekly_stats("2026-10-29")["metrics"]["cohort_interview_rate"] is None
    for _ in range(3):
        store.save("learning_card", validate_card({"title": "Long question " * 30, "due_at": "2020-01-01T00:00:00Z"}))
    result = service.learning_due(limit=1, offset=1)
    assert result["has_more"] and result["pagination_limit_reached"] and result["next_offset"] is None
    assert result["cards"][0]["title_truncated"] is True and len(result["cards"][0]["title"]) == 12


def test_version_cap_aborts_without_partial_statistics_or_mutation(store, tmp_path):
    row = store.save("plan", validate_plan({"title": "Version cap fixture", "acts": []}))
    for _ in range(2): row = store.save("plan", row["data"], row["id"], row["version"])
    service = query_service(store, tmp_path, max_stats_versions=1)
    service.clock = lambda: datetime.now(timezone.utc) + timedelta(hours=1)
    before = snapshot(store)
    with pytest.raises(DomainError, match="统计版本超过"): service.jobs_weekly_stats()
    assert snapshot(store) == before


def test_tools_metadata_strict_inputs_and_known_only(store, tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError
    seed(store)
    from rag_tech_retriever.platform.search_service import SearchService
    search = SearchService(store, connection=ModelConnection(tmp_path / "not-loaded.json"))
    server = mcp_routes.build_mcp_server(search, config(tmp_path))
    tools = asyncio.run(server.list_tools()); assert {x.name for x in tools} == BUSINESS_TOOLS | {"knowledge_search"}
    assert all(x.annotations.read_only_hint is True and x.annotations.destructive_hint is False for x in tools)
    assert all(x.input_schema["additionalProperties"] is False for x in tools)
    before = snapshot(store)
    for name, args in [("jobs_search", {"limit": True}), ("learning_due", {"limit": "1"}),
                       ("jobs_search", {"include_notes": True}), ("delete_all", {}), ("learning_review", {})]:
        with pytest.raises(ToolError): asyncio.run(server.call_tool(name, args))
    assert snapshot(store) == before


def test_separate_mcp_token_cannot_access_web_api_or_login(store, tmp_path, monkeypatch):
    mcp_token, owner_token = "m" * 40, "w" * 40
    monkeypatch.setenv("WORKSPACE_MCP_TOKEN", mcp_token)
    monkeypatch.setattr(mcp_routes, "_load_mcp_config", lambda: config(tmp_path))
    with TestClient(create_app(store, tmp_path, token=owner_token)) as client:
        header = {"Authorization": "Bearer " + mcp_token}
        assert client.get('/api/jobs', headers=header).status_code == 401
        assert client.post('/api/knowledge', headers=header, json={"data": {"title": "must not save", "content": "blocked"}}).status_code == 401
        assert client.post('/api/session', json={"token": mcp_token}).status_code == 401
        assert client.get('/api/jobs', headers={"Authorization": "Bearer " + owner_token}).status_code == 200
        response = client.post('/mcp/', headers={**header, "Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "readonly-test", "version": "1"}}})
        assert response.status_code == 200
        assert client.post('/mcp/', json={}).status_code == 401


def test_runtime_and_config_gate_fail_closed_for_business_credentials(store, tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(mcp_routes, "_load_mcp_config", lambda: cfg)
    monkeypatch.setenv("WORKSPACE_MCP_TOKEN", "")
    with pytest.raises(RuntimeError, match="独立WORKSPACE_MCP_TOKEN"): create_app(store, tmp_path, token="w" * 40)
    monkeypatch.setenv("WORKSPACE_MCP_TOKEN", "w" * 40)
    with pytest.raises(RuntimeError, match="不同于"): create_app(store, tmp_path, token="w" * 40)
    root = tmp_path / "gate"; (root / "config").mkdir(parents=True)
    for path in (ROOT / "config").glob("*.yaml"): (root / "config" / path.name).write_bytes(path.read_bytes())
    (root / "config/mcp.yaml").write_bytes(cfg.settings_path.read_bytes())
    secret = "DO_NOT_ECHO_THIS_SECRET" * 3
    report = configuration_report(root, "local", lambda k, default: {"WORKSPACE_ACCESS_TOKEN": secret, "WORKSPACE_MCP_TOKEN": secret}.get(k, default))
    assert not report["passed"] and secret not in json.dumps(report)
    assert any(x["id"] == "mcp_credential" and x["status"] == "fail" for x in report["checks"])


@pytest.mark.parametrize("token", ["short", " " * 40])
def test_bad_mcp_credential_never_starts_server(tmp_path, monkeypatch, token):
    monkeypatch.setenv("WORKSPACE_MCP_TOKEN", token)
    with pytest.raises(RuntimeError, match="独立令牌"):
        create_app(root=tmp_path, token="w" * 40)
