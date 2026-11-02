"""Isolated APIs, fake model and real local SDK server; no user records or API keys."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.snapshot import validate_snapshot
from rag_tech_retriever.platform.agent_capabilities import validate_schema
from rag_tech_retriever.platform.mcp_client import MCPGateway, ToolError
from rag_tech_retriever.platform.record_store import RecordStore
from rag_tech_retriever.platform.skill_registry import SkillRegistry

SKILL = "---\nname: knowledge-review\ndescription: 整理资料时使用\n---\n先检索已有知识，再提供引用；不自动写入。"


@pytest.fixture
def api(tmp_path):
    store = RecordStore("qa_caps_" + uuid4().hex[:12])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            yield client, tmp_path
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def agent(api, **fields):
    client, _ = api
    response = client.post("/api/agents", json={"data": {
        "title": "隔离工具助手", "generate": True, "scopes": ["personal"], **fields,
    }})
    assert response.status_code == 201, response.text
    return response.json()


def call(api, profile, name, arguments):
    client, _ = api
    response = client.post(f'/api/agents/{profile["id"]}/tools/call', json={
        "version": profile["version"], "name": name, "arguments": arguments,
    })
    assert response.status_code == 200, response.text
    return response.json()


def tool_call(name, arguments, call_id="test_call"):
    return {"tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments),
    }}], "content": None}


def test_skill_import_revision_and_binding_preserved_by_old_forms(api):
    client, _ = api
    assert client.get("/api/capabilities").json()["script_execution"] is False
    assert client.get("/api/mcp/servers").json() == []
    first = client.put("/api/skills/knowledge-review", json={"content": SKILL})
    assert first.status_code == 200
    revision = first.json()["revision"]
    assert client.put("/api/skills/knowledge-review", json={"content": SKILL}).status_code == 409
    assert client.put("/api/skills/knowledge-review", json={"content": SKILL, "revision": revision}).status_code == 200
    assert "instructions" not in client.get("/api/skills").json()[0]
    profile = agent(api, skill_ids=["knowledge-review"], tool_ids=["knowledge_search"])
    response = client.put(f'/api/agents/{profile["id"]}', json={"version": 1, "data": {"title": "旧表单编辑"}})
    assert response.json()["data"]["skill_ids"] == ["knowledge-review"]
    assert response.json()["data"]["tool_ids"] == ["knowledge_search"]
    assert {t["name"] for t in client.get(f'/api/agents/{profile["id"]}/tools').json()} == {"knowledge_search", "activate_skill"}


@pytest.mark.parametrize("content", ["no frontmatter", SKILL.replace("knowledge-review", "wrong"),
                                    SKILL.replace("description: 整理资料时使用", "description: []"), "a" * 65537],
                         ids=["missing_frontmatter", "name_mismatch", "bad_description", "oversize"])
def test_invalid_skill_import(api, content):
    client, _ = api
    assert client.put("/api/skills/knowledge-review", json={"content": content}).status_code in {400, 422}
    assert client.get("/api/skills").json() == []


def test_skill_path_escape_and_stale_update(tmp_path):
    registry = SkillRegistry(tmp_path / "skills")
    for name in ["../outside", "/absolute", "a/b", "A", "a--b"]:
        with pytest.raises(ValueError):
            registry.get(name)


def test_builtin_calls_enforce_grants_scopes_kind_and_schema(api):
    client, _ = api
    profile = agent(api, tool_ids=["knowledge_search", "knowledge_get", "knowledge_draft"])
    note = client.post("/api/knowledge", json={"data": {"title": "TESTSEARCH", "content": "隔离知识"}}).json()
    result = call(api, profile, "knowledge_search", {"query": "TESTSEARCH", "scope": "personal"})
    assert result["data"]["status"] == "completed"
    assert note["id"] in result["data"]["steps"][0]["detail"]
    assert call(api, profile, "knowledge_search", {"query": "x", "scope": "planning"})["data"]["status"] == "failed"
    assert call(api, profile, "planning_get", {"id": note["id"]})["data"]["status"] == "failed"
    assert call(api, profile, "knowledge_search", {"query": "x", "scope": "personal", "command": "no"})["data"]["status"] == "failed"
    private = client.app.state.store.save("diary", {"cipher": {"test": True}})
    forbidden = call(api, profile, "knowledge_get", {"id": private["id"]})
    assert forbidden["data"]["status"] == "failed"
    before = len(client.get("/api/knowledge").json())
    draft = call(api, profile, "knowledge_draft", {"title": "草稿", "content": "不入库"})
    assert '"saved": false' in draft["data"]["steps"][0]["detail"]
    assert len(client.get("/api/knowledge").json()) == before


def test_model_skill_activation_tool_result_and_final_answer(api, monkeypatch):
    client, _ = api
    client.put("/api/skills/knowledge-review", json={"content": SKILL})
    profile = agent(api, skill_ids=["knowledge-review"], tool_ids=["knowledge_draft"])
    captured = []
    messages = [tool_call("activate_skill", {"name": "knowledge-review"}, "skill1"),
                tool_call("knowledge_draft", {"title": "隔离草稿", "content": "有引用的内容"}, "draft1"),
                {"content": "草稿已准备，尚未保存。"}]

    async def model(history, specs):
        captured.append(deepcopy(history))
        return messages.pop(0)

    monkeypatch.setattr(client.app.state.agent_runtime, "model_chat", model)
    result = client.post(f'/api/agents/{profile["id"]}/run', json={"version": 1, "query": "整理这份知识"}).json()
    assert result["data"]["status"] == "completed"
    assert [s["title"] for s in result["data"]["steps"]] == ["activate_skill", "knowledge_draft"]
    assert "先检索已有知识" not in captured[0][0]["content"]  # progressive disclosure
    assert "先检索已有知识" in captured[1][-1]["content"]
    assert client.get(f'/api/agent-runs/{result["id"]}').json()["data"]["result"]["answer"]
    assert client.get("/api/knowledge").json() == []
    validate_snapshot(client.app.state.store.export())


def test_missing_model_and_loop_budget_are_not_success(api, monkeypatch):
    client, _ = api
    profile = agent(api, tool_ids=["knowledge_draft"])
    runtime = client.app.state.agent_runtime
    monkeypatch.setattr(runtime.connection, "load", lambda: {"api_key": "", "base_url": "", "model": ""})
    result = client.post(f'/api/agents/{profile["id"]}/run', json={"version": 1, "query": "hello"}).json()
    assert result["data"]["status"] == "failed"
    runtime.capabilities.limits["max_steps"] = 2
    count = 0

    async def model(*args):
        nonlocal count
        count += 1
        return tool_call("knowledge_draft", {"title": "草稿", "content": "正文"}, str(count))

    monkeypatch.setattr(runtime, "model_chat", model)
    result = client.post(f'/api/agents/{profile["id"]}/run', json={"version": 1, "query": "loop"}).json()
    assert result["data"]["status"] == "failed"
    assert count == 2


def test_permissions_cannot_be_smuggled_in_run_body(api):
    client, _ = api
    profile = agent(api)
    response = client.post(f'/api/agents/{profile["id"]}/run', json={
        "version": 1, "query": "x", "tool_ids": ["knowledge_get"], "command": "arbitrary",
    })
    assert response.status_code == 400
    assert client.post("/api/agents", json={"data": {"title": "bad", "tool_ids": ["shell"]}}).status_code == 400
    assert client.post("/api/agents", json={"data": {"title": "bad", "mcp_server_ids": ["unknown"]}}).status_code == 400


def test_mcp_schema_cannot_fetch_external_refs():
    with pytest.raises(ToolError):
        validate_schema({"$ref": "http://127.0.0.1/private"})


@pytest.fixture
def mcp_api(tmp_path):
    marker = tmp_path / "side-effect.txt"
    script = tmp_path / "fake_server.py"
    script.write_text('''from pathlib import Path
from mcp.server import MCPServer
mcp = MCPServer("isolated-qa")
@mcp.tool()
def echo(query: str) -> dict:
    return {"echo": query}
@mcp.tool()
def write_marker(value: str) -> str:
    with Path(MARKER).open("a", encoding="utf-8") as stream: stream.write(value+"\\n")
    return "written"
@mcp.tool()
def fail() -> str:
    raise ValueError("FAKE_SECRET_MUST_NOT_LEAK")
if __name__ == "__main__":
    import sys
    if len(sys.argv)>1: mcp.run(transport="streamable-http", host="127.0.0.1", port=int(sys.argv[1]))
    else: mcp.run()
'''.replace("MARKER", repr(str(marker))), encoding="utf-8")
    (tmp_path / "config").mkdir()
    cfg = {"limits": {"timeout_seconds": 12}, "servers": {"qa": {
        "transport": "stdio", "command": sys.executable, "args": [str(script)],
        "enabled": True, "trusted": True, "allow_tools": ["echo", "write_marker", "fail"],
        "readonly_tools": ["echo", "fail"],
    }}}
    (tmp_path / "config/agent-tools.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    store = RecordStore("qa_mcp_" + uuid4().hex[:12])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            yield client, tmp_path, marker
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def test_real_stdio_discovery_call_confirmation_and_duplicate_guard(mcp_api):
    client, root, marker = mcp_api
    basic = client.post("/api/agents", json={"data": {
        "title": "MCP隔离助手", "mcp_server_ids": ["qa"],
        "tool_ids": [MCPGateway.tool_name("qa", name) for name in ("echo", "write_marker", "fail")],
    }}).json()
    test = client.post("/api/mcp/servers/qa/test")
    assert test.status_code == 200, test.text
    tools = {t["remote_name"]: t["name"] for t in test.json()["tools"]}
    result = call((client, root), basic, tools["echo"], {"query": "fake-hello"})
    assert result["data"]["status"] == "completed", result
    assert result["data"]["steps"][0]["duration_ms"] > 0
    assert "fake-hello" in result["data"]["steps"][0]["detail"]
    pending = call((client, root), basic, tools["write_marker"], {"value": "approved-once"})
    assert pending["data"]["status"] == "awaiting_confirmation"
    assert not marker.exists()
    endpoint = f'/api/agent-runs/{pending["id"]}/confirm'
    payload = {"version": pending["version"], "approve": True}
    approved = client.post(endpoint, json=payload)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "completed"
    assert marker.read_text(encoding="utf-8") == "approved-once\n"
    assert client.post(endpoint, json=payload).status_code == 409
    assert marker.read_text(encoding="utf-8") == "approved-once\n"
    failed = call((client, root), basic, tools["fail"], {})
    assert failed["data"]["status"] == "failed"
    assert "FAKE_SECRET_MUST_NOT_LEAK" not in json.dumps(failed)


def test_confirmation_rejects_forged_snapshot_grants(mcp_api):
    client, root, marker = mcp_api
    profile = client.post("/api/agents", json={"data": {"title": "MCP助手", "mcp_server_ids": ["qa"],
        "tool_ids": [MCPGateway.tool_name("qa", "write_marker")]}}).json()
    tools = client.get(f'/api/agents/{profile["id"]}/tools').json()
    write = next(t["name"] for t in tools if t.get("remote_name") == "write_marker")
    row = call((client, root), profile, write, {"value": "must-not-run"})
    forged = deepcopy(row["data"])
    forged["agent"]["data"]["scopes"] = ["docs"]
    updated = client.app.state.store.save("workflow_run", forged, row["id"], row["version"])
    response = client.post(f'/api/agent-runs/{row["id"]}/confirm', json={"version": updated["version"], "approve": True})
    assert response.status_code == 409
    assert not marker.exists()


def test_real_streamable_http_client_and_no_secret_in_public_metadata(mcp_api, free_tcp_port, monkeypatch):
    client, root, _ = mcp_api
    script = root / "fake_server.py"
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen([sys.executable, str(script), str(free_tcp_port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    try:
        deadline = time.monotonic() + 12
        while True:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", free_tcp_port)) == 0:
                    break
            assert process.poll() is None and time.monotonic() < deadline, "isolated HTTP server failed startup"
            time.sleep(0.1)
        monkeypatch.setenv("QA_MCP_TEST_AUTH", "Bearer FAKE_HTTP_SECRET")
        gateway = client.app.state.context.capabilities.mcp
        gateway.servers["qa"] = {"transport": "streamable_http", "url": f"http://127.0.0.1:{free_tcp_port}/mcp",
            "enabled": True, "trusted": True, "headers_env": {"Authorization": "QA_MCP_TEST_AUTH"},
            "allow_tools": ["echo"], "readonly_tools": ["echo"]}
        response = client.post("/api/mcp/servers/qa/test")
        assert response.status_code == 200, response.text
        name = response.json()["tools"][0]["name"]
        profile = agent((client, root), mcp_server_ids=["qa"], tool_ids=[name])
        row = call((client, root), profile, name, {"query": "over-http"})
        assert row["data"]["status"] == "completed"
        assert "over-http" in row["data"]["steps"][0]["detail"]
        assert "FAKE_HTTP_SECRET" not in client.get("/api/mcp/servers").text
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_mcp_untrusted_service_and_remote_plain_http_are_rejected(mcp_api):
    client, _, marker = mcp_api
    gateway = client.app.state.context.capabilities.mcp
    gateway.servers["qa"]["trusted"] = False
    assert client.post("/api/mcp/servers/qa/test").status_code == 400
    gateway.servers["qa"] = {"enabled": True, "trusted": True, "transport": "streamable_http",
        "url": "http://example.invalid/mcp"}
    assert client.post("/api/mcp/servers/qa/test").status_code == 400
    assert not marker.exists()


def test_mcp_timeout_is_a_safe_failure_and_process_is_closed(mcp_api):
    client, _, marker = mcp_api
    gateway = client.app.state.context.capabilities.mcp
    gateway.limits["timeout_seconds"] = 1
    gateway.servers["qa"]["args"] = ["-c", "import time; time.sleep(60)"]
    started = time.monotonic()
    response = client.post("/api/mcp/servers/qa/test")
    assert response.status_code == 503, response.text
    assert time.monotonic() - started < 10
    assert not marker.exists()


def test_new_api_auth_csrf_and_validation_do_not_echo_input(api):
    client, root = api
    with TestClient(create_app(client.app.state.store, root, token="test-workspace-token")) as locked:
        assert locked.get("/api/capabilities").status_code == 401
        assert locked.post("/api/skills/github/preview", json={"repo_url": "https://github.com/a/b"}).status_code == 401
        headers = {"Authorization": "Bearer test-workspace-token"}
        assert locked.get("/api/capabilities", headers=headers).status_code == 200
        rejected = locked.put("/api/skills/knowledge-review", json={"content": SKILL},
                              headers={**headers, "Origin": "https://attacker.invalid"})
        assert rejected.status_code == 403
        invalid = locked.post("/api/agents/nonexistent/run", json={"query": "FAKE_PRIVATE_INPUT", "version": "bad"}, headers=headers)
        assert invalid.status_code == 400 and "FAKE_PRIVATE_INPUT" not in invalid.text


def test_agent_runs_are_not_misrendered_as_old_ingest_runs(api):
    client, _ = api
    profile = agent(api, tool_ids=["knowledge_draft"])
    row = call(api, profile, "knowledge_draft", {"title": "草稿", "content": "内容"})
    assert row["id"] in {r["id"] for r in client.get("/api/agent-runs").json()}
    assert row["id"] not in {r["id"] for r in client.get("/api/workflow-runs").json()}
    assert client.get(f'/api/workflow-runs/{row["id"]}').status_code == 404


def test_openai_compatible_http_tool_loop_uses_actual_wire_format(api, monkeypatch):
    client, _ = api
    profile = agent(api, tool_ids=["knowledge_draft"])
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(body)
            message = tool_call("knowledge_draft", {"title": "HTTP草稿", "content": "虚拟正文"}) if len(observed) == 1 else {"content": "已准备草稿，未入库"}
            payload = json.dumps({"choices": [{"message": message}]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = client.app.state.agent_runtime
        monkeypatch.setattr(runtime.connection, "load", lambda: {"model": "fake-model", "api_key": "FAKE_KEY",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1"})
        response = client.post(f'/api/agents/{profile["id"]}/run', json={"version": 1, "query": "准备知识草稿"})
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "completed"
        assert observed[0]["tools"][0]["function"]["name"] == "knowledge_draft"
        assert observed[1]["messages"][-1]["role"] == "tool"
        assert "FAKE_KEY" not in response.text
        assert client.get("/api/knowledge").json() == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mcp_grants_are_per_tool_and_permission_revocation_blocks_confirmation(mcp_api):
    client, root, marker = mcp_api
    profile = agent((client, root), mcp_server_ids=["qa"], tool_ids=[MCPGateway.tool_name("qa", "write_marker")])
    tools = client.get(f'/api/agents/{profile["id"]}/tools').json()
    assert len(tools) == 1 and tools[0]["remote_name"] == "write_marker"
    denied = call((client, root), profile, MCPGateway.tool_name("qa", "echo"), {"query": "not-granted"})
    assert denied["data"]["status"] == "failed"
    pending = call((client, root), profile, tools[0]["name"], {"value": "revoked"})
    client.put(f'/api/agents/{profile["id"]}', json={"version": 1, "data": {"mcp_server_ids": [], "tool_ids": []}})
    response = client.post(f'/api/agent-runs/{pending["id"]}/confirm', json={"version": pending["version"], "approve": True})
    assert response.status_code == 409 and not marker.exists()
