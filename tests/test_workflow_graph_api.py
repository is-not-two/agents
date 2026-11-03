"""Isolated PostgreSQL checks for DAG approval and resume upload endpoints."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.record_store import RecordStore

TEXT = """张三
教育经历
本科 计算机科学与技术
项目经历
使用 Python、FastAPI、PostgreSQL 开发 RAG 知识库。
专业技能
Python、FastAPI、PostgreSQL、Docker
"""


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_graph_" + uuid4().hex[:12])
    with TestClient(create_app(store, tmp_path, token="")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def test_graph_workflow_pauses_for_approval_and_resumes(api):
    flow = api.post("/api/workflows", json={"data": {
        "title": "带审批的 DAG", "kind": "graph",
        "nodes": [{"id": "input", "type": "input"}, {"id": "approve", "type": "approval", "message": "确认继续"},
                  {"id": "merge", "type": "merge"}],
        "edges": [["input", "approve"], ["approve", "merge"]],
    }})
    assert flow.status_code == 201, flow.text
    flow = flow.json()
    run = api.post(f"/api/workflows/{flow['id']}/run", json={"version": flow["version"], "input": {"query": "x"}})
    assert run.status_code == 200, run.text
    run = run.json()
    assert run["data"]["status"] == "awaiting_confirmation" and run["data"]["pending_node"] == "approve"
    confirmed = api.post(f"/api/workflow-runs/{run['id']}/confirm", json={"version": run["version"], "approve": True})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "completed"
    assert confirmed.json()["data"]["node_status"]["merge"] == "completed"


def test_invalid_graph_is_rejected_before_saving(api):
    response = api.post("/api/workflows", json={"data": {
        "title": "环", "kind": "graph",
        "nodes": [{"id": "input", "type": "input"}, {"id": "a", "type": "merge"}, {"id": "b", "type": "merge"}],
        "edges": [["input", "a"], ["a", "b"], ["b", "a"]],
    }})
    assert response.status_code == 400
    assert api.get("/api/workflows").json() == []


def test_resume_upload_document_diff_and_jd_analysis(api):
    lead = api.post("/api/jobs/leads", json={"data": {
        "title": "AI Agent 工程师", "company": "示例公司",
        "jd_text": "岗位要求\n1. 熟悉 Python、FastAPI、PostgreSQL。\n2. 有 RAG 经验者优先。",
    }}).json()
    first = api.post("/api/jobs/resumes/upload",
                     files={"file": ("resume.txt", TEXT.encode(), "text/plain")}, data={"title": "v1"})
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["data"]["parse_status"] == "parsed" and first["data"]["document_id"]
    document = api.get(f"/api/jobs/resumes/{first['id']}/document").json()
    assert "项目经历" in [section["title"] for section in document["sections"]]
    assert "Python" in document["skills"]
    second = api.post("/api/jobs/resumes/upload",
                      files={"file": ("resume2.txt", TEXT.replace("Docker", "Docker、K8s").encode(), "text/plain")},
                      data={"title": "v2"}).json()
    diff = api.get(f"/api/jobs/resumes/{second['id']}/diff?against={first['id']}").json()
    assert diff["added_lines"] >= 0 and diff["diff"]
    analysis = api.post(f"/api/jobs/resumes/{first['id']}/analyze", json={"lead_id": lead["id"]}).json()
    assert "Python" in analysis["matched_skills"] and "FastAPI" in analysis["matched_skills"]
    assert analysis["analysis"]["quality_verified"] is False
