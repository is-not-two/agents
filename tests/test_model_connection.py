"""模型连接的私有持久化、错误脱敏与实际 HTTP 生成链路。"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.fixture
def provider():
    """仅本机的模拟供应商，不使用真实密钥或外部网络。"""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("Authorization"), payload))
            model = payload["model"]
            self.send_response(401 if model == "denied" else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if model == "denied":
                self.wfile.write(json.dumps({"error": self.headers.get("Authorization")}).encode())
            elif model == "bad":
                self.wfile.write(b'{"unexpected":true}')
            else:
                self.wfile.write(
                    json.dumps({"choices": [{"message": {"content": "模拟回答 [1]"}}]}).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def connection_api(tmp_path, monkeypatch):
    for name in ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    store = RecordStore("qa_model_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            yield client, store, tmp_path
    finally:
        with store.transaction() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cursor.execute(f"DROP TABLE IF EXISTS {store.records}")


def settings(client, base, **changes):
    """读取当前版本并构造不涉及真实密钥的连接。"""
    return {
        "base_url": base,
        "model": "demo",
        "api_key": "dummy-private-key",
        "revision": client.get("/api/model-connection").json()["revision"],
        **changes,
    }


def test_save_redaction_restart_and_blank_key_preserves(connection_api, provider):
    client, store, root = connection_api
    base, _ = provider
    payload = settings(client, base + "/chat/completions")
    saved = client.put("/api/model-connection", json=payload)
    assert saved.status_code == 200
    assert saved.json()["base_url"] == base
    assert saved.json()["configured"] and saved.json()["has_api_key"]
    assert "dummy-private-key" not in saved.text
    path = root / "data/local/llm-connection.json"
    assert json.loads(path.read_text())["api_key"] == "dummy-private-key"
    updated = client.put(
        "/api/model-connection", json=settings(client, base, api_key="", model="updated")
    )
    assert updated.status_code == 200
    assert json.loads(path.read_text())["api_key"] == "dummy-private-key"
    with TestClient(create_app(store, root, token="")) as restarted:
        metadata = restarted.get("/api/model-connection")
        assert metadata.json()["model"] == "updated"
        assert "dummy-private-key" not in metadata.text
        assert restarted.get("/api/status").json()["llm_configured"]
    assert "dummy-private-key" not in client.get("/api/export").text
    assert "dummy-private-key" not in client.get("/api/export?format=markdown").text


def test_draft_test_does_not_save_and_errors_do_not_echo_secret(connection_api, provider):
    client, _, root = connection_api
    base, calls = provider
    for model, ok in [("demo", True), ("denied", False), ("bad", False)]:
        response = client.post(
            "/api/model-connection/test", json=settings(client, base, model=model)
        )
        assert response.status_code == 200 and response.json()["ok"] is ok
        assert "dummy-private-key" not in response.text
    assert calls[0][0] == "/v1/chat/completions"
    assert calls[0][1] == "Bearer dummy-private-key"
    assert not (root / "data/local/llm-connection.json").exists()
    malformed = client.put("/api/model-connection", json=[{"api_key": "dummy-private-key"}])
    assert malformed.status_code == 400
    assert "dummy-private-key" not in malformed.text


def test_saved_connection_is_used_by_generation_without_restart(connection_api, provider):
    client, _, _ = connection_api
    base, calls = provider
    assert client.put("/api/model-connection", json=settings(client, base)).status_code == 200
    assert (
        client.post(
            "/api/knowledge", json={"data": {"title": "连接验收", "content": "模型连接已接入"}}
        ).status_code
        == 201
    )
    result = client.post(
        "/api/query", json={"query": "连接验收", "scope": "personal", "generate": True}
    )
    assert result.status_code == 200
    assert result.json()["answer"] == "模拟回答 [1]"
    assert calls[-1][1] == "Bearer dummy-private-key"
    assert calls[-1][2]["model"] == "demo"
    assert "dummy-private-key" not in result.text


def test_concurrent_save_rejects_stale_version(connection_api, provider):
    client, _, _ = connection_api
    base, _ = provider
    payload = settings(client, base)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(
            pool.map(
                lambda _: client.put("/api/model-connection", json=payload).status_code, range(2)
            )
        )
    assert sorted(codes) == [200, 409]
    assert client.post("/api/model-connection/test", json=payload).status_code == 409


def test_validation_and_connection_failure_keep_saved_settings(
    connection_api, provider, monkeypatch
):
    client, _, _ = connection_api
    base, _ = provider
    assert client.put("/api/model-connection", json=settings(client, base)).status_code == 200
    before = client.get("/api/model-connection").json()
    for url in [
        "file:///tmp/test",
        "https://key@example.com/v1",
        "https://example.com/?key=secret",
    ]:
        response = client.put("/api/model-connection", json=settings(client, url))
        assert response.status_code == 400
        assert "dummy-private-key" not in response.text
    assert client.get("/api/model-connection").json() == before

    def timeout(*args, **kwargs):
        raise TimeoutError("dummy-private-key must not be echoed")

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=timeout))
    failed = client.post("/api/model-connection/test", json=settings(client, base))
    assert failed.status_code == 200 and not failed.json()["ok"]
    assert "dummy-private-key" not in failed.text
    assert client.get("/api/model-connection").json() == before


def test_private_file_corruption_does_not_break_workspace(connection_api):
    client, _, root = connection_api
    path = root / "data/local/llm-connection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("broken-private-file")
    assert client.get("/api/model-connection").status_code == 503
    assert client.get("/api/status").status_code == 200
    assert not client.get("/api/status").json()["llm_configured"]


def test_auth_protects_credentials_and_connection_test(connection_api, provider):
    _, store, root = connection_api
    base, calls = provider
    with TestClient(create_app(store, root, token="workspace-token")) as secured:
        payload = {"base_url": base, "api_key": "dummy-private-key", "model": "demo"}
        assert secured.get("/api/model-connection").status_code == 401
        assert secured.put("/api/model-connection", json=payload).status_code == 401
        assert secured.post("/api/model-connection/test", json=payload).status_code == 401
        assert not calls
