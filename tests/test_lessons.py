"""谨记名单测试：领域校验（纯函数）+ API CRUD（真实 PostgreSQL，qa_ 隔离表）。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.lessons import LESSON_CATEGORIES, validate_lesson
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordStore

BASE = {"title": "把 staging 当生产库执行了删表", "category": "操作"}


def test_validate_lesson_defaults_and_categories():
    result = validate_lesson(BASE)
    assert result["title"] == BASE["title"]
    assert result["category"] == "操作"
    assert result["content"] == "" and result["remedy"] == ""
    assert set(LESSON_CATEGORIES) == {"技术", "操作", "判断", "习惯", "其他"}
    # 自定义类型：≤20 字非空即可
    assert validate_lesson({**BASE, "category": "  自定义类型  "})["category"] == "自定义类型"


def test_validate_lesson_rejects_bad_input():
    for bad in ({**BASE, "title": "  "}, {**BASE, "category": ""}, {**BASE, "category": "x" * 21}, {**BASE, "category": 5}):
        with pytest.raises(DomainError):
            validate_lesson(bad)


@pytest.fixture
def api(tmp_path):
    store = RecordStore("qa_lessons_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_lesson_crud_trash_and_restore(api) -> None:
    created = api.post(
        "/api/lessons",
        json={"data": {**BASE, "content": "周报模板没看仔细", "remedy": " destructive 命令先 --dry-run"}},
    )
    assert created.status_code == 201
    row = created.json()
    assert row["data"]["category"] == "操作"

    assert len(api.get("/api/lessons").json()) == 1
    # 更新：类型改为判断，携带版本
    updated = api.put(
        f"/api/lessons/{row['id']}",
        json={"data": {**BASE, "category": "判断"}, "version": row["version"]},
    )
    assert updated.json()["data"]["category"] == "判断"
    # 旧版本更新 → 409 冲突
    stale = api.put(
        f"/api/lessons/{row['id']}",
        json={"data": BASE, "version": row["version"]},
    )
    assert stale.status_code == 409
    # 软删除 → 回收站可见、列表不可见
    deleted = api.delete(f"/api/records/{row['id']}?version={updated.json()['version']}")
    assert deleted.status_code == 200
    assert api.get("/api/lessons").json() == []
    trash = api.get("/api/lessons?trash=true").json()
    assert len(trash) == 1
    # 通用恢复接口
    history = api.get(f"/api/records/{row['id']}/history").json()
    target = next(v for v in history if not v["deleted"])
    restored = api.post(
        f"/api/records/{row['id']}/restore",
        json={"target_version": target["version"], "current_version": trash[0]["version"]},
    )
    assert restored.status_code == 200
    assert len(api.get("/api/lessons").json()) == 1


def test_lesson_appears_in_admin_stats_and_export(api) -> None:
    api.post("/api/lessons", json={"data": BASE})
    stats = api.get("/api/admin/stats").json()
    assert stats["kinds"]["lesson"]["active"] == 1
    assert api.get("/api/status").json()["lessons_count"] == 1
    export = api.get("/api/export?format=markdown").text
    assert "【谨记·操作】" in export and "删表" in export
