"""确认建卡、复习调度、原子审计、幂等与导出边界。"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.learning import next_schedule, validate_card
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.snapshot import validate_snapshot
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.mark.parametrize("rating", [0, 1, 2, 3])
def test_schedule_is_due_relative_to_actual_review_not_missed_days(rating):
    config = ConfigLoader.load_default()
    policy = ConfigLoader(config.settings_path.parent / "learning.yaml").get("learning")
    card = validate_card({"title": "实际问题", "due_at": "2020-01-01T00:00:00Z"})
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    result = next_schedule(card, rating, now.isoformat(), policy)
    assert datetime.fromisoformat(result["due_at"]) > now
    assert result["interval_days"] == policy["first_days"][rating]
    assert result["repetitions"] == (0 if rating == 0 else 1)
    assert result["ease"] >= policy["min_ease"]


@pytest.mark.parametrize("bad", [{"source": "interview"}, {"repetitions": True}, {"ease": float("nan")}, {"paused": "true"}, {"due_at": "2026-10-28"}, {"interval_days": -1}])
def test_bad_cards_are_rejected(bad):
    with pytest.raises(DomainError):
        validate_card({"title": "实际问题", "due_at": "2020-01-01T00:00:00Z", **bad})


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_learning_" + uuid4().hex[:10])
    with TestClient(create_app(store, tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def create_card(api):
    response = api.post("/api/learning/cards", json={"data": {"title": "幂等边界", "answer_ref": "查证项目中实际实现", "due_at": "2020-01-01T00:00:00Z"}})
    assert response.status_code == 201, response.text
    return response.json()


def report(api):
    lead = api.post("/api/jobs/leads", json={"data": {"title": "后端", "company": "示例"}}).json()
    app = api.post("/api/jobs/applications", json={"data": {"lead_id": lead["id"], "status": "applied"}}).json()
    api.patch(f"/api/jobs/applications/{app['id']}", json={"version": 1, "data": {"status": "interviewing"}})
    return api.post("/api/jobs/reports", json={"data": {"application_id": app["id"], "questions": [{"q": "事务如何回滚"}], "weak_points": ["事务边界", "外部副作用"]}}).json()


def test_confirmed_candidates_are_versioned_and_deduplicated(api):
    source = report(api)
    assert api.get("/api/learning/cards").json()["cards"] == []
    url = f"/api/learning/from-interview/{source['id']}"
    body = {"version": 1, "points": ["事务边界"], "confirmation": ""}
    assert api.post(url, json=body).status_code == 400
    assert api.get("/api/learning/cards").json()["cards"] == []
    body["confirmation"] = "确认创建复习卡"
    created = api.post(url, json=body)
    assert created.status_code == 200, created.text
    card = created.json()["created"][0]
    assert card["data"]["source_id"] == source["id"] and card["data"]["source_version"] == 1
    repeated = api.post(url, json=body).json()
    assert not repeated["created"] and repeated["reused"][0]["id"] == card["id"]
    assert api.post(url, json={**body, "version": 2}).status_code == 409
    assert api.post(url, json={**body, "points": ["虚构薄弱点"]}).status_code == 400
    assert len(api.get("/api/learning/cards").json()["cards"]) == 1
    validate_snapshot(api.get("/api/export").json())


def test_review_retry_and_concurrent_replay_only_advance_once(api):
    card = create_card(api)
    body = {"version": card["version"], "rating": 2, "request_id": uuid4().hex}
    url = f"/api/learning/cards/{card['id']}/review"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: api.post(url, json=body), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json()["replayed"] for r in results) == [False, True]
    current = api.get("/api/learning/cards").json()
    assert current["cards"][0]["version"] == 2 and not current["due_ids"]
    assert len(api.get(f"/api/learning/cards/{card['id']}/reviews").json()) == 1
    assert api.post(url, json={**body, "rating": 3}).status_code == 409
    assert api.post(url, json={**body, "version": 2, "request_id": uuid4().hex}).status_code == 409
    audit = api.get(f"/api/learning/cards/{card['id']}/reviews").json()[0]
    assert api.delete(f"/api/records/{audit['id']}?version=1").status_code == 409
    assert api.post(f"/api/records/{audit['id']}/restore", json={"target_version": 1, "current_version": 1}).status_code == 409
    validate_snapshot(api.get("/api/export").json())


def test_editing_cannot_forge_source_or_progress_and_conflicts_are_visible(api):
    card = create_card(api)
    path = f"/api/learning/cards/{card['id']}"
    assert api.put(path, json={"version": 1, "data": {"repetitions": 99}}).status_code == 400
    assert api.post("/api/learning/cards", json={"data": {"title": "伪造", "source": "interview"}}).status_code == 400
    response = api.put(path, json={"version": 1, "data": {"title": "修订问题", "paused": True}})
    assert response.status_code == 200
    assert api.put(path, json={"version": 1, "data": {"title": "旧版本"}}).status_code == 409
    assert api.get("/api/learning/cards").json()["due_ids"] == []
    assert api.post(path + "/review", json={"version": 2, "rating": True, "request_id": uuid4().hex}).status_code == 400


def test_card_archive_restore_and_snapshot_references(api):
    source = report(api)
    card = api.post(f"/api/learning/from-interview/{source['id']}", json={"version": 1, "points": ["事务边界"], "confirmation": "确认创建复习卡"}).json()["created"][0]
    assert api.delete(f"/api/records/{card['id']}?version=1").status_code == 200
    assert api.get("/api/learning/cards").json()["cards"] == []
    assert api.get("/api/learning/cards?trash=true").json()["cards"][0]["id"] == card["id"]
    assert api.post(f"/api/records/{card['id']}/restore", json={"target_version": 1, "current_version": 2}).status_code == 200
    snapshot = api.get("/api/export").json()
    validate_snapshot(snapshot)
    snapshot["records"] = [row for row in snapshot["records"] if row["id"] != source["id"]]
    assert api.post("/api/import/preview", json={"snapshot": snapshot}).status_code == 400
    assert "事务边界" in api.get("/api/export?format=markdown").text
