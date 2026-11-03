"""错误契约测试：统一信封 {detail, code, request_id} 与脱敏边界（批次 A）。

口径（OPTIMIZATION-DESIGN.md 批次 A）：
- 全部 /api 错误响应带稳定 code 与 request_id，detail 永远是用户可读字符串；
- 校验错误统一 400 VALIDATION_ERROR，绝不回显提交内容（任何路径，不再按 URL 特例）；
- request_id 与响应头 X-Request-ID 一致，可与访问日志关联。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.record_store import RecordStore, StorageError

ENVELOPE_KEYS = {"detail", "code", "request_id"}


@pytest.fixture
def api(tmp_path):
    store = RecordStore("qa_errcontract_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def assert_envelope(response, code: str, status: int) -> dict:
    assert response.status_code == status
    body = response.json()
    assert ENVELOPE_KEYS <= set(body)
    assert body["code"] == code
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["request_id"] == response.headers.get("X-Request-ID")
    assert body["request_id"]  # 非空，可与访问日志关联
    return body


def test_validation_error_envelope_and_no_input_echo(api):
    marker = "MARKER_" + uuid4().hex
    response = api.post(
        "/api/knowledge",
        json={"data": {"title": "t", "content": "c"}, "version": marker},
    )
    body = assert_envelope(response, "VALIDATION_ERROR", 400)
    assert marker not in response.text  # 脱敏：任何路径都不回显提交内容
    assert isinstance(body["fields"], list) and body["fields"]
    for field in body["fields"]:
        assert set(field) == {"loc", "msg", "type"}  # input/ctx/url 已剥离


def test_validation_error_on_formerly_special_cased_path(api):
    """历史按 URL 特例脱敏的路径（/api/agents/*）现在同样走统一契约。"""
    marker = "FAKE_PRIVATE_INPUT_" + uuid4().hex
    response = api.post(
        "/api/agents/nonexistent/run",
        json={"query": marker, "version": "bad"},
    )
    assert_envelope(response, "VALIDATION_ERROR", 400)
    assert marker not in response.text


def test_not_found_and_version_conflict_envelopes(api):
    missing = api.delete(f"/api/records/{uuid4().hex}?version=1")
    assert_envelope(missing, "NOT_FOUND", 404)

    created = api.post("/api/knowledge", json={"data": {"title": "t", "content": "c"}}).json()
    stale = api.put(
        f"/api/knowledge/{created['id']}",
        json={"data": {"title": "t2", "content": "c2"}, "version": created["version"] + 5},
    )
    assert_envelope(stale, "VERSION_CONFLICT", 409)


def test_unauthorized_and_forbidden_envelopes(tmp_path):
    store = RecordStore("qa_errcontract_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store=store, root=tmp_path, token="qa-secret-token")) as locked:
            unauthorized = locked.get("/api/knowledge")
            assert_envelope(unauthorized, "UNAUTHORIZED", 401)

            forbidden = locked.post(
                "/api/knowledge",
                json={"data": {"title": "t", "content": "c"}},
                headers={
                    "Authorization": "Bearer qa-secret-token",
                    "Origin": "https://attacker.invalid",
                },
            )
            assert_envelope(forbidden, "FORBIDDEN", 403)
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE {store.versions}")
            cur.execute(f"DROP TABLE {store.records}")


def test_payload_too_large_envelope(api):
    big = "x" * (2 * 1024 * 1024 + 64)
    response = api.post("/api/knowledge", json={"data": {"title": "t", "content": big}})
    assert_envelope(response, "PAYLOAD_TOO_LARGE", 413)


def test_rate_limited_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_RATE_LIMIT_PER_MINUTE", "2")
    store = RecordStore("qa_errcontract_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
            assert client.get("/api/session").status_code == 200
            assert client.get("/api/session").status_code == 200
            limited = client.get("/api/session")
            body = assert_envelope(limited, "RATE_LIMITED", 429)
            assert limited.headers.get("Retry-After")
            assert body["detail"]  # 文案仍在 detail，code 供归因
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE {store.versions}")
            cur.execute(f"DROP TABLE {store.records}")


def test_http_exception_envelope(api):
    response = api.post("/api/query", json={"query": "q", "scope": "not-a-scope"})
    assert_envelope(response, "VALIDATION_ERROR", 400)


def test_storage_tool_and_internal_mapping(api, monkeypatch):
    def raise_storage(*args, **kwargs):
        raise StorageError("存储故障演练")

    monkeypatch.setattr(api.app.state.store, "list", raise_storage)
    assert_envelope(api.get("/api/knowledge"), "STORAGE_UNAVAILABLE", 503)

    def raise_tool(*args, **kwargs):
        raise ToolError("工具故障演练")

    monkeypatch.setattr(api.app.state.store, "list", raise_tool)
    assert_envelope(api.get("/api/knowledge"), "TOOL_FAILURE", 503)


def test_internal_error_hides_details(tmp_path):
    store = RecordStore("qa_errcontract_" + uuid4().hex[:10])
    try:
        with TestClient(
            create_app(store=store, root=tmp_path, token=""),
            raise_server_exceptions=False,
        ) as client:

            def raise_runtime(*args, **kwargs):
                raise RuntimeError("secret-internal-detail")

            client.app.state.store.list = raise_runtime
            response = client.get("/api/knowledge")
            body = assert_envelope(response, "INTERNAL", 500)
            assert "secret-internal-detail" not in response.text
            assert "Traceback" not in response.text
            assert body["detail"] == "服务器内部错误，请稍后重试"
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE {store.versions}")
            cur.execute(f"DROP TABLE {store.records}")


def test_method_not_allowed_uses_envelope(api):
    """Starlette 抛出的 405 也必须带稳定 code 与 request_id，而不是裸 detail。"""
    response = api.patch("/api/knowledge/anything", json={"data": {}})
    body = assert_envelope(response, "METHOD_NOT_ALLOWED", 405)
    assert body["detail"] == "该接口不支持此方法"


def test_unknown_api_path_uses_envelope(api):
    """不存在的 /api 路径同样走统一信封，前端才能按 code 归因。"""
    response = api.get("/api/definitely-not-here")
    body = assert_envelope(response, "NOT_FOUND", 404)
    assert body["detail"] == "接口不存在"
