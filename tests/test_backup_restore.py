"""恢复预览、并发保护与保护快照的真实 PostgreSQL 验证。"""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.stage_journal import JournalError
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.fixture
def backup_api(tmp_path):
    store = RecordStore("qa_backup_" + uuid4().hex[:10])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            yield client
    finally:
        with store.transaction() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {store.versions}")
            cursor.execute(f"DROP TABLE IF EXISTS {store.records}")


def note(api, title="原内容"):
    return api.post("/api/knowledge", json={"data": {"title": title, "content": "内容"}}).json()


def test_public_backup_preserves_private_records_and_history(backup_api) -> None:
    """Public restore must neither export nor remove unrelated encrypted records."""
    api = backup_api
    store = api.app.state.context.store
    note(api)
    snapshot = api.get("/api/export?format=json").json()
    private = store.save("wish", {"cipher": "isolated-test-cipher"})
    private = store.save("wish", {"cipher": "updated-test-cipher"}, private["id"], private["version"])
    diary = store.save("diary", {"cipher": "isolated-diary"})
    store.delete(diary["id"], diary["version"])
    public = api.get("/api/export?format=json").json()
    assert not {"wish", "diary"} & {r["kind"] for r in public["records"]}
    assert private["id"] not in {v["record_id"] for v in public["versions"]}
    assert api.get("/api/export?format=markdown").status_code == 200
    note(api, "恢复时移除")
    result = preview(api, snapshot)
    assert restore(api, result).status_code == 200
    assert store.get(private["id"]) == private
    assert len(store.history(private["id"])) == 2
    assert store.get(diary["id"], include_deleted=True)["deleted"]


def test_public_restore_rejects_id_collision_with_private_record(backup_api) -> None:
    """An imported public record cannot overwrite a private record with the same ID."""
    api = backup_api
    store = api.app.state.context.store
    private = store.save("wish", {"cipher": "isolated-test-cipher"})
    payload = {"format_version": 1, "records": [{
        "id": private["id"], "kind": "knowledge", "data": {"title": "错误覆盖", "content": "x"},
    }]}
    result = preview(api, payload)
    stages_before = api.get("/api/stages").json()
    assert restore(api, result).status_code == 409
    assert api.get("/api/stages").json() == stages_before
    assert store.get(private["id"]) == private


def preview(api, snapshot):
    response = api.post("/api/import/preview", json={"snapshot": snapshot})
    assert response.status_code == 200
    return response.json()


def restore(api, result):
    return api.post(
        "/api/import",
        json={
            "confirmation": "恢复数据",
            "snapshot": result["snapshot"],
            "expected_revision": result["revision"],
            "snapshot_hash": result["snapshot_hash"],
        },
    )


def test_preview_restore_and_protection_snapshot_roundtrip(backup_api):
    api = backup_api
    original = note(api)
    exported = api.get("/api/export").json()
    api.put(
        "/api/knowledge/" + original["id"],
        json={"version": 1, "data": {"title": "新版内容", "content": "修改"}},
    )
    extra = note(api, "备份后新建")
    before = api.app.state.store.export()
    result = preview(api, exported)
    assert result["counts"] == {"added": 0, "updated": 1, "removed": 1, "unchanged": 0}
    assert not api.app.state.journal.list()
    assert api.app.state.store.export() == before
    response = restore(api, result)
    assert response.status_code == 200
    assert response.json()["restored_records"] == 2
    safety_id = response.json()["safety_stage_id"]
    assert api.app.state.journal.data_snapshot(safety_id) == before
    assert api.get("/api/knowledge").json()[0]["data"]["title"] == "原内容"
    assert api.app.state.store.get(extra["id"], True)["deleted"]
    assert len(api.get(f"/api/records/{original['id']}/history").json()) == 3
    reverted = api.post(f"/api/stages/{safety_id}/restore-data", json={"confirmation": "恢复数据"})
    assert reverted.status_code == 200
    assert {r["data"]["title"] for r in api.get("/api/knowledge").json()} == {
        "新版内容",
        "备份后新建",
    }


def test_new_changes_and_file_changes_reject_without_artifacts(backup_api):
    api = backup_api
    row = note(api)
    result = preview(api, api.get("/api/export").json())
    api.put(
        "/api/knowledge/" + row["id"],
        json={"version": 1, "data": {"title": "预览后的修改", "content": "保留"}},
    )
    assert restore(api, result).status_code == 409
    assert not api.app.state.journal.list()
    assert api.get("/api/knowledge").json()[0]["data"]["title"] == "预览后的修改"
    changed = preview(api, api.get("/api/export").json())
    changed["snapshot"]["records"][0]["data"]["title"] = "预览后换文件"
    assert restore(api, changed).status_code == 400
    assert not api.app.state.journal.list()


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"format_version": True, "records": []},
        {"format_version": 1, "records": [{"kind": [], "id": "bad", "data": {}}]},
        {
            "format_version": 1,
            "records": [{"kind": "plan", "id": "bad", "data": {"title": "坏规划", "kind": []}}],
        },
    ],
)
def test_invalid_file_is_rejected_before_snapshot(backup_api, snapshot):
    api = backup_api
    note(api)
    before = api.app.state.store.export()
    assert api.post("/api/import/preview", json={"snapshot": snapshot}).status_code == 400
    assert (
        api.post("/api/import", json={"snapshot": snapshot, "confirmation": "恢复数据"}).status_code
        == 400
    )
    assert api.app.state.store.export() == before
    assert not api.app.state.journal.list()


def test_protection_failure_prevents_write_and_secret_stays_private(backup_api, monkeypatch):
    api = backup_api
    row = note(api)
    target = deepcopy(api.get("/api/export").json())
    target["records"][0]["data"]["title"] = "将要恢复"
    result = preview(api, target)
    connection = api.app.state.search.connection
    connection.save(
        {
            "base_url": "https://example.invalid/v1",
            "model": "demo",
            "api_key": "dummy-backup-secret",
            "revision": connection.load()["revision"],
        }
    )
    original_secret_file = connection.path.read_bytes()
    start = api.app.state.journal.start

    def fail(*args, **kwargs):
        raise JournalError("测试保护快照失败")

    monkeypatch.setattr(api.app.state.journal, "start", fail)
    assert restore(api, result).status_code == 400
    assert api.app.state.store.get(row["id"])["data"]["title"] == "原内容"
    monkeypatch.setattr(api.app.state.journal, "start", start)
    assert restore(api, result).status_code == 200
    assert connection.path.read_bytes() == original_secret_file


def test_large_preview_uses_import_limit_and_no_change_summary(backup_api):
    api = backup_api
    body = "文" * 100000
    snapshot = {
        "format_version": 1,
        "records": [
            {
                "id": f"large-{i}",
                "kind": "knowledge",
                "data": {"title": f"大文件{i}", "content": body},
            }
            for i in range(8)
        ],
    }
    result = preview(api, snapshot)
    assert result["counts"]["added"] == 8
    assert restore(api, result).status_code == 200
    again = preview(api, api.get("/api/export").json())
    assert again["counts"] == {"added": 0, "updated": 0, "removed": 0, "unchanged": 8}
    assert api.get("/api/import/options").json()["max_file_bytes"] > 2097152
