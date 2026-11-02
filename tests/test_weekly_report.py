"""周报事件时间、投递分组、空分母与模型统计降级。"""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.life_planning import validate_plan
from rag_tech_retriever.platform.record_store import RecordStore, StorageError
from rag_tech_retriever.platform.weekly_report import WeeklyReport


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_weekly_" + uuid4().hex[:10])
    with TestClient(create_app(store, tmp_path, token="")) as client:
        yield client, tmp_path, store
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def service(api):
    client, root, store = api
    return WeeklyReport(root, store, client.app.state.search.connection)


def seed_application(api, applied_at, interview_at=None):
    client, _, _ = api
    lead = client.post(
        "/api/jobs/leads",
        json={"data": {"title": "岗位", "company": uuid4().hex, "jd_text": "熟悉 Python"}},
    ).json()
    app = client.post(
        "/api/jobs/applications",
        json={"data": {"lead_id": lead["id"], "status": "applied", "applied_at": applied_at}},
    ).json()
    if interview_at:
        client.patch(
            f"/api/jobs/applications/{app['id']}",
            json={"version": 1, "data": {"status": "interviewing"}},
        )
        response = client.post(
            "/api/jobs/reports",
            json={
                "data": {
                    "application_id": app["id"],
                    "interviewed_at": interview_at,
                    "questions": [{"q": "幂等边界"}, {"q": "幂等边界"}],
                    "weak_points": ["外部副作用"],
                }
            },
        )
        assert response.status_code == 201, response.text
    return app


def test_empty_week_has_null_rate_and_view_does_not_persist_or_call_model(api):
    client, root, _ = api
    result = client.get("/api/jobs/report/weekly?day=2026-01-07")
    assert result.status_code == 200, result.text
    assert result.json()["current"]["week_start"] == "2026-01-05"
    assert result.json()["current"]["metrics"]["cohort_interview_rate"] is None
    assert not result.json()["saved"] and not (root / "data/local/weekly-reports").exists()
    assert client.get("/api/jobs/report/weekly?day=not-a-date").status_code == 400


def test_event_window_and_later_interviews_are_not_confused_with_weekly_new_interviews(api):
    seed_application(api, "2026-01-05T01:00:00+08:00", "2026-01-15T09:00:00+08:00")
    seed_application(api, "2025-12-31T10:00:00+08:00", "2026-01-06T09:00:00+08:00")
    report = service(api).report("2026-01-07", now=datetime(2026, 2, 1, tzinfo=timezone.utc))
    metrics = report["metrics"]
    assert report["window_start_utc"] == "2026-01-04T16:00:00+00:00"
    assert metrics["applications_submitted"] == 1 and metrics["interviews_recorded"] == 1
    assert metrics["cohort_interviewed"] == 1 and metrics["cohort_interview_rate"] == 1
    assert report["top_questions"] == [{"question": "幂等边界", "count": 1}]
    before_later_interview = service(api).report(
        "2026-01-07", now=datetime(2026, 1, 7, tzinfo=timezone.utc)
    )
    assert before_later_interview["metrics"]["cohort_interviewed"] == 0


def test_plan_current_done_is_not_counted_as_new_completion(api):
    _, _, store = api
    payload = validate_plan(
        {
            "title": "学习",
            "kind": "main",
            "acts": [
                {
                    "id": "a1",
                    "title": "阶段",
                    "nodes": [
                        {"id": "n1", "title": "已完成导入节点", "done": True},
                        {"id": "n2", "title": "待完成节点", "done": False},
                    ],
                }
            ],
        }
    )
    first = store.save("plan", payload)
    payload["acts"][0]["nodes"][1]["done"] = True
    store.save("plan", payload, first["id"], 1)
    # Synthetic event-time fixture: mutate only our owned QA versions table.
    with store.transaction() as cur:
        cur.execute(
            f"UPDATE {store.versions} SET created_at=%s WHERE record_id=%s",
            (datetime(2026, 1, 6, tzinfo=timezone.utc), first["id"]),
        )
    report = service(api).report("2026-01-07", now=datetime(2026, 1, 7, tzinfo=timezone.utc))
    assert report["metrics"]["plan_completion_events"] == 1


def test_save_stats_model_failure_and_weekly_outbox_are_idempotent(api, monkeypatch):
    client, root, _ = api
    seed_application(api, "2026-01-05T09:00:00+08:00")
    body = {"day": "2026-01-07", "mode": "statistics", "confirmation": "生成并保存周报"}
    first = client.post("/api/jobs/report/weekly", json=body)
    assert first.status_code == 200, first.text
    assert "本周投递：1" in first.json()["markdown"]
    repeated = client.post("/api/jobs/report/weekly", json=body).json()
    assert repeated["reused"] and repeated["as_of"] == first.json()["as_of"]
    assert (root / "data/local/weekly-reports/2026-01-05.json").exists()
    calls = []

    def failed(*args):
        calls.append(1)
        raise StorageError("模型不可用，保留统计")

    monkeypatch.setattr("rag_tech_retriever.platform.weekly_report.request_json", failed)
    model_body = {"day": "2026-01-07", "mode": "model", "confirmation": "发送统计进行周报增强"}
    fallback = client.post("/api/jobs/report/weekly", json=model_body)
    assert fallback.status_code == 200 and fallback.json()["mode"] == "fallback_statistics"
    assert fallback.json()["metrics"]["applications_submitted"] == 1
    assert (
        client.post("/api/jobs/report/weekly", json=model_body).json()["reused"] and len(calls) == 1
    )
    notice = {"day": "2026-01-07", "confirmation": "加入周报通知队列"}
    first_notice = client.post("/api/jobs/report/weekly/notify", json=notice).json()
    repeated_notice = client.post("/api/jobs/report/weekly/notify", json=notice).json()
    assert (
        first_notice["notification"]["id"] == repeated_notice["notification"]["id"]
        and repeated_notice["reused"]
    )
    assert first_notice["notification"]["data"]["status"] == "pending"


def test_model_only_selects_real_metric_keys_and_cannot_replace_numbers(api, monkeypatch):
    weekly = service(api)

    def ranked(*args):
        return {"focus_keys": ["followups_due", "reviews_due"]}, {
            "model": "mock",
            "usage": "unknown",
            "cost": "unknown",
        }

    monkeypatch.setattr("rag_tech_retriever.platform.weekly_report.request_json", ranked)
    result = weekly.generate("2026-01-07", "model", "发送统计进行周报增强")
    assert result["mode"] == "model" and result["metrics"]["applications_submitted"] == 0
    assert result["focus_keys"] == ["followups_due", "reviews_due"]
    assert result["quality_verified"] is False
