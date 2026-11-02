"""admin 管理接口与 chat 对话检索接口测试（真实 PostgreSQL，qa_ 前缀隔离表）。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.fixture
def api(tmp_path):
    store = RecordStore("qa_admchat_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_admin_stats_shape_and_counts(api) -> None:
    api.post("/api/knowledge", json={"data": {"title": "t", "content": "c", "tags": ["a", "b"]}})
    api.post("/api/knowledge", json={"data": {"title": "t2", "content": "c", "tags": []}})
    row = api.delete("/api/records/" + api.get("/api/knowledge").json()[0]["id"] + "?version=1").json()
    assert row.get("deleted") is True
    stats = api.get("/api/admin/stats").json()
    assert stats["storage"] == "PostgreSQL"
    assert stats["kinds"]["knowledge"]["active"] == 1
    assert stats["kinds"]["knowledge"]["trash"] == 1
    assert set(stats["kinds"]) >= {"knowledge", "plan", "agent_profile", "workflow"}
    assert isinstance(stats["stages_count"], int)
    assert stats["rate_limit_per_minute"] == 120
    assert "available" in stats["vector"]  # 可用或显式降级都合法


def test_chat_valid_and_rejects_bad_payload(api) -> None:
    ok = api.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "检索调试工具怎么用"}], "scope": "docs"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["turns"] == 1
    assert "hits" in body and "engine" in body and body["query"] == "检索调试工具怎么用"

    # 多轮：取最后一条用户消息检索
    multi = api.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "前面的问题"},
                {"role": "assistant", "content": "回答"},
                {"role": "user", "content": "协议号查询"},
            ]
        },
    )
    assert multi.status_code == 200
    assert multi.json()["turns"] == 3

    for bad in (
        {"messages": []},
        {"messages": [{"role": "system", "content": "x"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": [{"role": "user", "content": "x"}], "scope": "bad"},
        {"messages": [{"role": "user", "content": "x"}], "mode": "bad"},
    ):
        assert api.post("/api/chat", json=bad).status_code == 400


def test_chat_blank_last_user_rejected(api) -> None:
    # 全是 assistant 消息：无 user 内容，应 400 而非 500
    only_ast = {"messages": [{"role": "assistant", "content": "hi"}]}
    assert api.post("/api/chat", json=only_ast).status_code == 400
