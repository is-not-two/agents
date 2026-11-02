"""求职领域反例和隔离 PostgreSQL 业务事务闭环。"""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.jobs import (
    timestamp,
    validate_lead,
    validate_report,
    validate_resume,
)
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.snapshot import validate_snapshot
from rag_tech_retriever.platform.record_store import RecordStore


def test_pure_lead_metadata_and_utc():
    assert validate_lead({"title": " Python 后端 ", "company": "示例"})["title"] == "Python 后端"
    assert timestamp("2026-10-28T18:00:00+08:00", "时间") == "2026-10-28T10:00:00+00:00"
    assert validate_resume({"title": "后端 v1", "file_hash": "A" * 64})["file_hash"] == "a" * 64


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.com", "http://[", "//example.com"])
def test_bad_source_link(url):
    with pytest.raises(DomainError):
        validate_lead({"title": "后端", "company": "示例", "source_url": url})


@pytest.mark.parametrize("value", ["2026-10-28T18:00", "yesterday", "2026-02-30T12:00Z", [], 5])
def test_timezone_or_type_cannot_be_guessed(value):
    with pytest.raises(DomainError):
        timestamp(value, "时间")


@pytest.mark.parametrize("payload", [{"questions": []}, {"round": True, "questions": [{"q": "实际问题"}]}, {"questions": [{"q": "", "rating": 1}]}, {"questions": [{"q": "问题", "rating": True}]}])
def test_bad_report(payload):
    with pytest.raises(DomainError):
        validate_report({"application_id": "a", **payload})


@pytest.fixture
def api(tmp_path):
    # These integration tests must never connect to an existing user's database.
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression", "Use scripts/ci_verify.py with its owned disposable database"
    store = RecordStore("qa_jobs_" + uuid4().hex[:12])
    with TestClient(create_app(store, tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def create(api, name, data):
    response = api.post("/api/jobs/" + name, json={"data": data})
    assert response.status_code == 201, response.text
    return response.json()


def patch(api, row, data):
    response = api.patch(f"/api/jobs/applications/{row['id']}", json={"version": row["version"], "data": data})
    assert response.status_code == 200, response.text
    return response.json()


def lead(api, title="Python 实习"):
    return create(api, "leads", {"title": title, "company": "真实场景测试公司", "jd_text": "FastAPI 与 PostgreSQL", "source_url": "https://example.com/jobs"})


def test_full_jobs_roundtrip_versions_snapshot_and_plaintext_export(api):
    job = lead(api)
    resume = create(api, "resumes", {"title": "Python 岗位 v1", "file_hash": "b" * 64, "highlights": ["真实 RAG 项目"]})
    application = create(api, "applications", {"lead_id": job["id"], "status": "applied", "channel": "官网", "resume_version_id": resume["id"], "follow_up_at": "2020-01-01T09:00:00+08:00"})
    assert application["data"]["applied_at"] and application["data"]["title"].endswith("Python 实习")
    stale_version = application["version"]
    application = patch(api, application, {"status": "following", "notes": "一周后跟进"})
    stale = api.patch(f"/api/jobs/applications/{application['id']}", json={"version": stale_version, "data": {"notes": "不能覆盖"}})
    assert stale.status_code == 409
    assert api.get("/api/jobs").json()["application"][0]["data"]["notes"] == "一周后跟进"
    application = patch(api, application, {"status": "interviewing"})
    report = create(api, "reports", {"application_id": application["id"], "round": 1, "questions": [{"q": "如何防止重复写入？", "answer_summary": "讲清幂等边界", "rating": 2}], "weak_points": ["恢复窗口"], "next_actions": ["补齐反例测试"]})
    overview = api.get("/api/jobs").json()
    assert overview["counts"]["interviewing"] == 1 and overview["due_application_ids"] == [application["id"]]
    assert overview["interview_report"][0]["data"]["weak_points"] == ["恢复窗口"]
    exported = api.get("/api/export").json()
    assert validate_snapshot(exported)["records"]
    assert "恢复窗口" in api.get("/api/export?format=markdown").text
    # No implicit card or external action is introduced by saving an interview.
    assert {row["kind"] for row in exported["records"]} == {"job_lead", "application", "resume_version", "interview_report"}
    assert len(api.get(f"/api/records/{application['id']}/history").json()) == 3
    assert report["data"]["interviewed_at"]
    assert api.get(f"/api/jobs/applications/{application['id']}/reports").json()[0]["id"] == report["id"]
    assert api.get(f"/api/jobs/applications/{application['id']}").json()["id"] == application["id"]
    assert api.get(f"/api/jobs/leads/{application['id']}").status_code == 404
    assert api.delete(f"/api/records/{resume['id']}?version=1").status_code == 409
    assert api.post(f"/api/jobs/applications/{application['id']}/reports", json={"data": {**report["data"], "application_id": "wrong"}}).status_code == 400


def test_references_state_and_duplicate_creation_are_not_silent(api):
    job = lead(api)
    for body in ({"lead_id": "missing"}, {"lead_id": job["id"], "resume_version_id": "missing"}):
        assert api.post("/api/jobs/applications", json={"data": body}).status_code == 404
    assert api.post("/api/jobs/applications", json={"data": {"lead_id": job["id"], "status": "offered"}}).status_code == 400
    application = create(api, "applications", {"lead_id": job["id"]})
    assert api.post("/api/jobs/applications", json={"data": {"lead_id": job["id"]}}).status_code == 409
    assert api.patch(f"/api/jobs/applications/{application['id']}", json={"data": {"status": "applied"}}).status_code == 409
    assert api.patch(f"/api/jobs/applications/{application['id']}", json={"version": 1, "data": {"status": "offered"}}).status_code == 400
    other = lead(api, "另一个岗位")
    assert api.patch(f"/api/jobs/applications/{application['id']}", json={"version": 1, "data": {"lead_id": other["id"]}}).status_code == 400
    assert api.put(f"/api/jobs/leads/{application['id']}", json={"version": 1, "data": job["data"]}).status_code == 404


def test_only_one_concurrent_application_is_created(api):
    job = lead(api)
    def submit(_):
        return api.post("/api/jobs/applications", json={"data": {"lead_id": job["id"]}}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(submit, range(2)))
    assert sorted(statuses) == [201, 409]
    assert len(api.get("/api/jobs/applications").json()) == 1


def test_archive_and_restore_preserve_relationships(api):
    job = lead(api)
    application = create(api, "applications", {"lead_id": job["id"], "status": "applied"})
    assert api.delete(f"/api/records/{job['id']}?version=1").status_code == 409
    application = patch(api, application, {"status": "interviewing"})
    report = create(api, "reports", {"application_id": application["id"], "questions": [{"q": "真实问题"}]})
    assert api.delete(f"/api/records/{application['id']}?version=2").status_code == 409
    for row in (report, application, job):
        assert api.delete(f"/api/records/{row['id']}?version={row['version']}").status_code == 200
    assert len(api.get("/api/jobs?trash=true").json()["job_lead"]) == 1
    assert api.post(f"/api/records/{application['id']}/restore", json={"target_version": 2, "current_version": 3}).status_code == 404
    for row in (job, application, report):
        response = api.post(f"/api/records/{row['id']}/restore", json={"target_version": row["version"], "current_version": row["version"] + 1})
        assert response.status_code == 200, response.text
    validate_snapshot(api.get("/api/export").json())


def test_snapshot_rejects_orphans_and_private_reference(api):
    job = lead(api)
    create(api, "applications", {"lead_id": job["id"]})
    snapshot = api.get("/api/export").json()
    snapshot["records"] = [row for row in snapshot["records"] if row["kind"] != "job_lead"]
    assert api.post("/api/import/preview", json={"snapshot": snapshot}).status_code == 400
    private = api.app.state.store.save("diary", {"cipher": "not accessed"})
    assert api.post("/api/jobs/applications", json={"data": {"lead_id": private["id"]}}).status_code == 404


def test_terminal_states_do_not_generate_due_followups(api):
    job = lead(api)
    application = create(api, "applications", {"lead_id": job["id"], "status": "applied", "follow_up_at": "2020-01-01T00:00:00Z"})
    application = patch(api, application, {"status": "interviewing"})
    application = patch(api, application, {"status": "offered"})
    assert api.get("/api/jobs").json()["due_application_ids"] == []
    assert api.patch(f"/api/jobs/applications/{application['id']}", json={"version": application["version"], "data": {"status": "applied"}}).status_code == 400
