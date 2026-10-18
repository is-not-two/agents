"""真实 API+PostgreSQL 的端到端数据链路、访问控制与降级反例。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.fixture
def api(tmp_path):
    store = RecordStore("qa_api_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_tree_nodes_persistence_conflicts_and_branch_guards(api) -> None:
    """树层级独立于依赖；拒绝循环/陈旧版本/悬空引用，历史仍可恢复。"""
    row = api.post("/api/plans", json={"data": {"title": "主线", "acts": []}}).json()
    path = f"/api/plans/{row['id']}"
    first = api.post(path + "/nodes", json={"data": {"title": "目标"}, "version": 1})
    assert first.status_code == 201
    parent = first.json()["data"]["acts"][0]["nodes"][0]["id"]
    second = api.post(
        path + "/nodes",
        json={
            "data": {"title": "下一步", "parent_id": parent},
            "version": 2,
        },
    )
    assert second.status_code == 201
    child = second.json()["data"]["acts"][0]["nodes"][1]
    assert child["parent_id"] == parent and child["state"] == "available"
    assert (
        api.put(
            path + "/nodes/" + parent,
            json={
                "data": {"parent_id": child["id"]},
                "version": 3,
            },
        ).status_code
        == 400
    )
    assert (
        api.put(
            path + "/nodes/" + parent,
            json={
                "data": {"title": "旧页面"},
                "version": 1,
            },
        ).status_code
        == 409
    )
    assert api.delete(path + f"/nodes/{parent}?version=3").status_code == 400
    third = api.post(
        path + "/nodes",
        json={
            "data": {"title": "外部依赖", "requires": [child["id"]]},
            "version": 3,
        },
    ).json()
    external = third["data"]["acts"][0]["nodes"][2]
    assert api.delete(path + f"/nodes/{parent}?version=4&cascade=true").status_code == 400
    assert (
        api.put(
            path + "/nodes/" + external["id"],
            json={
                "data": {"requires": []},
                "version": 4,
            },
        ).status_code
        == 200
    )
    deleted = api.delete(path + f"/nodes/{parent}?version=5&cascade=true")
    assert deleted.status_code == 200
    assert len(deleted.json()["data"]["acts"][0]["nodes"]) == 1
    restored = api.post(
        f"/api/records/{row['id']}/restore",
        json={
            "target_version": 3,
            "current_version": 6,
        },
    ).json()
    assert restored["data"]["acts"][0]["nodes"][1]["parent_id"] == parent


def test_planning_date_can_be_omitted_added_and_cleared(api) -> None:
    """只填名称可创建；日期可后补和清空，并真实持久化。"""
    plan = api.post("/api/plans", json={"data": {"title": "可选日期"}}).json()
    path = f"/api/plans/{plan['id']}/nodes"
    created = api.post(path, json={"data": {"title": "读书"}, "version": 1})
    assert created.status_code == 201
    node = created.json()["data"]["acts"][0]["nodes"][0]
    assert node["due_date"] == ""
    dated = api.put(
        path + "/" + node["id"],
        json={
            "data": {"due_date": "2027-01-01"},
            "version": 2,
        },
    )
    assert dated.status_code == 200
    cleared = api.put(
        path + "/" + node["id"],
        json={
            "data": {"due_date": ""},
            "version": 3,
        },
    )
    assert cleared.status_code == 200
    assert api.get("/api/plans").json()[0]["data"]["acts"][0]["nodes"][0]["due_date"] == ""


def test_branch_preview_delete_undo_and_stale_versions(api) -> None:
    """预检只读且列明依赖；删除和撤销都不能覆盖后续改动。"""
    row = api.post(
        "/api/plans",
        json={
            "data": {
                "title": "规划",
                "acts": [
                    {
                        "id": "a",
                        "title": "任务",
                        "nodes": [
                            {"id": "parent", "title": "父任务"},
                            {"id": "child", "title": "子任务", "parent_id": "parent"},
                            {"id": "outside", "title": "其他任务", "requires": ["child"]},
                        ],
                    },
                ],
            }
        },
    ).json()
    path = f"/api/plans/{row['id']}/nodes/parent"
    preview = api.get(path + "/delete-preview").json()
    assert preview["version"] == 1
    assert [n["id"] for n in preview["affected"]] == ["parent", "child"]
    assert preview["blockers"] == [{"id": "outside", "title": "其他任务"}]
    assert not preview["can_delete"]
    assert len(api.get(f"/api/records/{row['id']}/history").json()) == 1
    assert api.delete(path + "?version=1&cascade=true").status_code == 400
    changed = api.put(
        f"/api/plans/{row['id']}/nodes/outside",
        json={
            "version": 1,
            "data": {"requires": []},
        },
    )
    assert changed.status_code == 200
    assert api.get(path + "/delete-preview").json()["can_delete"]
    assert api.delete(path + "?version=1&cascade=true").status_code == 409
    assert api.delete(path + "?version=2&cascade=true").status_code == 200
    restored = api.post(
        f"/api/records/{row['id']}/restore",
        json={
            "target_version": 2,
            "current_version": 3,
        },
    )
    assert restored.status_code == 200
    assert len(restored.json()["data"]["acts"][0]["nodes"]) == 3
    assert (
        api.post(
            f"/api/records/{row['id']}/restore",
            json={
                "target_version": 2,
                "current_version": 3,
            },
        ).status_code
        == 409
    )
    assert api.get(f"/api/plans/{row['id']}/nodes/missing/delete-preview").status_code == 404


def test_web_save_history_restore_and_export(api) -> None:
    saved = api.post(
        "/api/knowledge",
        json={"data": {"title": "协议笔记", "content": "setupProgress 统计口径", "tags": ["技术"]}},
    )
    assert saved.status_code == 201
    row = saved.json()
    updated = api.put(
        "/api/knowledge/" + row["id"],
        json={"data": {"title": "新版笔记", "content": "新正文"}, "version": 1},
    )
    assert updated.json()["version"] == 2
    assert (
        api.put(
            "/api/knowledge/" + row["id"],
            json={"data": {"title": "旧页面", "content": "不覆盖"}, "version": 1},
        ).status_code
        == 409
    )
    restored = api.post(
        f"/api/records/{row['id']}/restore", json={"target_version": 1, "current_version": 2}
    )
    assert restored.json()["data"]["title"] == "协议笔记"
    assert len(api.get(f"/api/records/{row['id']}/history").json()) == 3
    exported = api.get("/api/export")
    assert exported.json()["records"][0]["data"]["title"] == "协议笔记"
    assert len(exported.json()["versions"]) == 3
    assert "协议笔记" in api.get("/api/export?format=markdown").text
    found = api.post("/api/query", json={"query": "setupProgress", "scope": "personal"}).json()
    assert found["hits"][0]["id"] == row["id"]


def test_stage_snapshot_restores_data_without_deleting_history(api) -> None:
    before = api.post("/api/knowledge", json={"data": {"title": "最初", "content": "内容"}}).json()
    stage = api.post("/api/stages", json={"title": "测试大阶段", "objective": "保存快照"}).json()
    api.put(
        f"/api/knowledge/{before['id']}",
        json={"data": {"title": "修改后", "content": "修改"}, "version": 1},
    )
    result = api.post(f"/api/stages/{stage['id']}/restore-data", json={"confirmation": "恢复数据"})
    assert result.status_code == 200
    assert api.get("/api/knowledge").json()[0]["data"]["title"] == "最初"
    assert len(api.get(f"/api/records/{before['id']}/history").json()) == 3


def test_vector_failure_falls_back_to_text(api, monkeypatch) -> None:
    search = api.app.state.search

    def fail(query):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr(search, "_vector_search", fail)
    response = api.post("/api/query", json={"query": "setupProgress", "mode": "vector"}).json()
    assert response["engine"] == "全文匹配"
    assert response["notes"] and response["hits"]


def test_api_auth_and_cross_origin_rejection(tmp_path) -> None:
    store = RecordStore("qa_auth_" + uuid4().hex[:10])
    with TestClient(create_app(store, tmp_path, token="test-secret")) as client:
        assert client.get("/api/knowledge").status_code == 401
        assert client.post("/api/session", json={"token": "bad"}).status_code == 401
        assert client.post("/api/session", json={"token": "test-secret"}).status_code == 200
        assert client.get("/api/knowledge").status_code == 200
        assert (
            client.post(
                "/api/knowledge",
                json={"data": {"title": "x", "content": "y"}},
                headers={"Origin": "https://example.invalid"},
            ).status_code
            == 403
        )
        client.delete("/api/session")
        assert client.get("/api/knowledge").status_code == 401
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_blank_input_and_invalid_plan_rejected(api) -> None:
    assert (
        api.post("/api/knowledge", json={"data": {"title": "", "content": ""}}).status_code == 400
    )
    assert api.post("/api/query", json={"query": "  "}).status_code == 400
    assert (
        api.post("/api/plans", json={"data": {"title": "计划", "kind": "daily"}}).status_code == 400
    )


def test_bad_import_leaves_existing_content_untouched(api) -> None:
    api.post("/api/knowledge", json={"data": {"title": "保留我", "content": "原文"}})
    bad = {
        "format_version": 1,
        "records": [
            {
                "id": "bad",
                "kind": "plan",
                "data": {"title": "非法规划", "kind": "invalid", "acts": []},
            }
        ],
    }
    response = api.post("/api/import", json={"confirmation": "恢复数据", "snapshot": bad})
    assert response.status_code == 400
    assert api.get("/api/knowledge").json()[0]["data"]["title"] == "保留我"
