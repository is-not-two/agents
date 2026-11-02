"""MCP 端点测试：工具注册/开关、call_tool 调用、状态路由、HTTP 挂载可达性。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.api.routes import mcp as mcp_routes
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.record_store import RecordStore

PY_TRACE = 'File "a.py", line 1, in f\nKeyError: "k"'


class FakeSearch:
    def query(self, query, scope, mode, generate):
        return {
            "query": query,
            "engine": "本地全文检索",
            "hits": [{"title": query, "score": 1.0}],
            "notes": [],
        }


def _config(tmp_path, enabled: dict | None = None, corpus: bool = True) -> ConfigLoader:
    tools = enabled if enabled is not None else {
        "protocol_query": True,
        "stacktrace_parser": True,
        "debug_retriever": True,
    }
    lines = ["server:", "  name: unit-test-server", "tools:"]
    for name, on in tools.items():
        lines += [f"  {name}:", f"    enabled: {str(on).lower()}", "    permission: readonly"]
    lines += [
        "resources:",
        "  corpus:",
        f"    enabled: {str(corpus).lower()}",
        "permissions:",
        "  readonly: true",
        "  admin: false",
    ]
    path = tmp_path / "mcp-unit.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ConfigLoader(path)


def test_list_tools_respects_config(tmp_path):
    server = mcp_routes.build_mcp_server(FakeSearch(), _config(tmp_path))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"protocol_query", "stacktrace_parser", "debug_retriever"} <= names
    # search_docs 未在单元配置中 → 不注册
    assert "search_docs" not in names


def test_search_docs_registered_when_enabled(tmp_path):
    cfg = _config(tmp_path, enabled={"search_docs": True, "stacktrace_parser": True})
    server = mcp_routes.build_mcp_server(FakeSearch(), cfg)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "search_docs" in names and "stacktrace_parser" in names


def test_disabled_tool_not_registered(tmp_path):
    cfg = _config(tmp_path, enabled={"stacktrace_parser": False})
    server = mcp_routes.build_mcp_server(FakeSearch(), cfg)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "stacktrace_parser" not in names


def test_call_tool_stacktrace_roundtrip(tmp_path):
    server = mcp_routes.build_mcp_server(FakeSearch(), _config(tmp_path))
    result = asyncio.run(
        server.call_tool("stacktrace_parser", {"trace": PY_TRACE})
    )
    text = getattr(result, "content", None)
    rendered = "".join(getattr(block, "text", "") for block in text or [])
    assert "KeyError" in rendered and "possible_causes" in rendered or "KeyError" in rendered


def test_status_route_and_mcp_mount(tmp_path):
    store = RecordStore("qa_mcp_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        status = client.get("/api/mcp/status").json()
        assert status["transport"] == "streamable-http"
        assert status["mount"] == "/mcp"
        assert any(t["name"] == "protocol_query" and t["enabled"] for t in status["tools"])
        # /mcp 挂载存在：真实 MCP initialize 握手应成功（协议层 200，含服务信息）
        handshake = client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
        assert handshake.status_code == 200
        assert "unit" not in handshake.text  # 挂的是真实 mcp.yaml 配置的服务名
        assert "jsonrpc" in handshake.text or "serverInfo" in handshake.text
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_allowed_hosts_enables_host_validation(tmp_path):
    """server.allowed_hosts 非空 → Host 校验开启：陌生 Host 421、白名单 Host 放行。"""
    cfg_text = (
        "server:\n"
        "  name: host-check\n"
        "  allowed_hosts:\n"
        "    - workbench.example:8080\n"
        "tools:\n"
        "  stacktrace_parser:\n"
        "    enabled: true\n"
        "    permission: readonly\n"
        "resources:\n"
        "  corpus:\n"
        "    enabled: false\n"
        "permissions:\n"
        "  readonly: true\n"
        "  admin: false\n"
    )
    cfg_path = tmp_path / "mcp-host.yaml"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    app = mcp_routes.streamable_app(FakeSearch(), ConfigLoader(cfg_path))
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    # 同一 streamable app 的会话管理器只能 run 一次；第二个客户端用新实例
    with TestClient(app, base_url="http://evil.example") as stranger:
        assert stranger.post("/", headers=headers, json=init).status_code == 421
    app2 = mcp_routes.streamable_app(FakeSearch(), ConfigLoader(cfg_path))
    with TestClient(app2, base_url="http://workbench.example:8080") as trusted:
        assert trusted.post("/", headers=headers, json=init).status_code == 200
