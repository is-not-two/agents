"""真实 PostgreSQL + LangGraph 链路与冲突/降级/隔离反例。"""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.agent.workflow_service import WorkflowService, split_document
from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError, derive_plan, validate_plan
from rag_tech_retriever.domains.snapshot import validate_snapshot
from rag_tech_retriever.platform.record_store import RecordStore, VersionConflict


@pytest.fixture
def client(tmp_path):
    """测试表独立，失败也清理本次建立的表。"""
    store = RecordStore("qa_auto_" + uuid4().hex[:12])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as browser:
            yield browser
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def setup(client):
    assert client.post("/api/automation/setup").json()["created"]
    agent = client.get("/api/agents").json()[0]
    flows = {r["data"]["kind"]: r for r in client.get("/api/workflows").json()}
    return agent, flows


def test_setup_idempotent_and_agent_version_conflict(client):
    agent, flows = setup(client)
    assert not client.post("/api/automation/setup").json()["created"]
    assert len(client.get("/api/agents").json()) == 1
    data = {**agent["data"], "system_prompt": "用中文回答", "scopes": ["personal"]}
    changed = client.put(f"/api/agents/{agent['id']}", json={"data": data, "version": 1})
    assert changed.json()["version"] == 2
    assert client.put(f"/api/agents/{agent['id']}", json={"data": data, "version": 1}).status_code == 409
    assert len(flows) == 2


def test_answer_respects_agent_scopes_and_freezes_versions(client):
    agent, flows = setup(client)
    note = client.post("/api/knowledge", json={"data": {"title": "setupProgress", "content": "个人学习备注"}}).json()
    data = {**agent["data"], "scopes": ["personal"], "result_limit": 1}
    client.put(f"/api/agents/{agent['id']}", json={"data": data, "version": 1})
    run = client.post(f"/api/workflows/{flows['answer']['id']}/run", json={"version": 1, "input": {"query": "setupProgress"}}).json()
    assert run["data"]["status"] == "completed"
    assert [h["id"] for h in run["data"]["result"]["hits"]] == [note["id"]]
    assert run["data"]["agent"]["version"] == 2
    client.put(f"/api/agents/{agent['id']}", json={"data": {**data, "system_prompt": "新的指令"}, "version": 2})
    stored = client.get(f"/api/workflow-runs/{run['id']}").json()
    assert stored["data"]["agent"]["version"] == 2
    assert len(stored["data"]["steps"]) == 3
    assert "input" not in client.get("/api/workflow-runs").json()[0]["data"]


def test_generation_degrades_and_applies_role(client, monkeypatch):
    agent, flows = setup(client)
    captured = []
    def generate(query, hits, extra_prompt=""):
        captured.append(extra_prompt)
        return "", ["模拟模型暂不可用，保留引用"]
    monkeypatch.setattr(client.app.state.search, "generate_answer", generate)
    client.put(f"/api/agents/{agent['id']}", json={"data": {**agent['data'], "generate": True, "system_prompt": "先说明结论"}, "version": 1})
    run = client.post(f"/api/workflows/{flows['answer']['id']}/run", json={"version": 1, "input": {"query": "setupProgress"}}).json()
    assert run["data"]["status"] == "fallback" and run["data"]["result"]["hits"]
    assert captured == ["先说明结论"] and not run["data"]["result"]["answer"]


def test_no_evidence_does_not_generate(client, monkeypatch):
    agent, flows = setup(client)
    client.put(f"/api/agents/{agent['id']}", json={"data": {**agent['data'], "scopes": ["personal"], "generate": True}, "version": 1})
    def unexpected(*args):
        raise AssertionError("没有依据时禁止生成")
    monkeypatch.setattr(client.app.state.search, "generate_answer", unexpected)
    run = client.post(f"/api/workflows/{flows['answer']['id']}/run", json={"version": 1, "input": {"query": "不存在的内容"}}).json()
    assert run["data"]["steps"][-1]["status"] == "skipped"


def test_ingest_manual_selection_duplicate_confirm_and_snapshot(client):
    _, flows = setup(client)
    run = client.post(f"/api/workflows/{flows['ingest']['id']}/run", json={"version": 1, "input": {"title": "学习笔记", "content": "# 第一节\n内容 A\n# 第二节\n内容 B"}}).json()
    assert run["data"]["status"] == "awaiting_confirmation"
    assert not client.get("/api/knowledge").json()
    confirm = {"version": run["version"], "selected": [1]}
    saved = client.post(f"/api/workflow-runs/{run['id']}/confirm", json=confirm).json()
    assert saved["data"]["status"] == "confirmed"
    assert client.get("/api/knowledge").json()[0]["data"]["title"] == "第二节"
    assert client.post(f"/api/workflow-runs/{run['id']}/confirm", json=confirm).status_code == 409
    assert len(client.get("/api/knowledge").json()) == 1
    snapshot = client.get("/api/export").json()
    assert {r["kind"] for r in snapshot["records"]} == {"knowledge", "agent_profile", "workflow", "workflow_run"}
    validate_snapshot(snapshot)
    assert client.get("/api/export?format=markdown").status_code == 200
    assert client.post("/api/import", json={"confirmation": "恢复数据", "snapshot": snapshot}).status_code == 200


def test_concurrent_confirm_saves_only_once(client):
    _, flows = setup(client)
    run = client.post(f"/api/workflows/{flows['ingest']['id']}/run", json={"version": 1, "input": {"title": "资料", "content": "正文"}}).json()
    service = WorkflowService(client.app.state.store, client.app.state.search)
    def confirm(_):
        try:
            return service.confirm(run["id"], run["version"], [0])["data"]["status"]
        except VersionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(confirm, range(2)))
    assert sorted(outcomes) == ["confirmed", "conflict"]
    assert len(client.get("/api/knowledge").json()) == 1


@pytest.mark.parametrize("patch", [{"scopes": []}, {"scopes": [{}]}, {"mode": {}}, {"result_limit": True}])
def test_invalid_agent_contract(client, patch):
    assert client.post("/api/agents", json={"data": {"title": "角色", **patch}}).status_code == 400


def test_invalid_reference_stale_workflow_and_failed_parse(client):
    _, flows = setup(client)
    assert client.post("/api/workflows", json={"data": {"title": "坏引用", "agent_id": "missing"}}).status_code == 404
    assert client.post(f"/api/workflows/{flows['answer']['id']}/run", json={"version": 99, "input": {"query": "query"}}).status_code == 409
    assert not client.get("/api/workflow-runs").json()
    run = client.post(f"/api/workflows/{flows['ingest']['id']}/run", json={"version": 1, "input": {"title": "空标题", "content": "# 只有标题"}}).json()
    assert run["data"]["status"] == "failed"
    assert run["data"]["steps"][-1]["status"] == "failed"
    assert not client.get("/api/knowledge").json()


def test_parser_fences_limits_and_chapter_states():
    chunks = split_document("# 一\n正文\n```\n# 代码中的标题\n```\n# 二\n内容", "资料", "", 200)
    assert len(chunks) == 2 and "代码中的标题" in chunks[0]["content"]
    with pytest.raises(DomainError):
        split_document("# 只有标题", "资料", "", 200)
    plan = derive_plan(validate_plan({"title": "主线", "acts": [{"title": "空章节", "description": "目标", "nodes": []}]}))
    assert plan["acts"][0]["state"] == "draft" and plan["acts"][0]["description"] == "目标"


def test_model_request_role_and_invalid_response_fallback(client, monkeypatch):
    settings = {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "test-model"}
    original = ConfigLoader.env
    monkeypatch.setattr(ConfigLoader, "env", lambda self, key, default=None: settings[key] if key in settings else original(self, key, default))
    requests = []
    def fake_open(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": None}}]}).encode())
    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=fake_open))
    answer, notes = client.app.state.search.generate_answer("问题", [{"title": "依据", "content": "正文"}], "本轮角色指令")
    assert not answer and notes
    assert "本轮角色指令" in requests[0]["messages"][0]["content"]
    assert "[1] 依据" in requests[0]["messages"][1]["content"]


def test_large_real_export_can_be_imported(client):
    _, flows = setup(client)
    for index in range(3):
        run = client.post(f"/api/workflows/{flows['ingest']['id']}/run", json={"version": 1, "input": {"title": f"资料{index}", "content": "文" * 100000}})
        assert run.status_code == 200
    snapshot = client.get("/api/export").json()
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) > 2097152
    restored = client.post("/api/import", json={"confirmation": "恢复数据", "snapshot": snapshot})
    assert restored.status_code == 200


def test_schema_upgrade_preserves_existing_and_invalid_run_backup_rejected(client):
    store = client.app.state.store
    note = store.save("knowledge", {"title": "原内容", "content": "保留"})
    with store.transaction() as cur:
        cur.execute(f"ALTER TABLE {store.records} DROP CONSTRAINT {store.records}_kind_check")
        cur.execute(f"ALTER TABLE {store.records} ADD CONSTRAINT {store.records}_kind_check CHECK (kind IN ('knowledge','plan'))")
    store.ensure_schema()
    store.ensure_schema()
    assert store.get(note["id"])["data"]["content"] == "保留"
    setup(client)
    snapshot = client.get("/api/export").json()
    snapshot["records"].append({"id": "bad-run", "kind": "workflow_run", "data": {
        "title": "坏记录", "workflow_id": "x", "kind": "ingest", "status": "confirmed",
        "steps": [], "input": {}, "result": {"chunks": [{"title": "内容", "content": "正文"}]}
    }})
    assert client.post("/api/import", json={"confirmation": "恢复数据", "snapshot": snapshot}).status_code == 400
    assert store.get(note["id"])["data"]["content"] == "保留"
