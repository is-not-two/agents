"""原文引证、自填证据边界、私密文件 CAS 与真实回环模型协议。"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.job_analysis import model_analysis, rules_analysis, validate_profile
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.private_json import PrivateJson
from rag_tech_retriever.platform.record_store import RecordStore, StorageError, VersionConflict


def taxonomy():
    settings = ConfigLoader.load_default()
    return ConfigLoader(settings.settings_path.parent / "jobs.yaml").get("jobs.taxonomy")


@pytest.mark.parametrize(
    "jd",
    [
        "本科及以上，熟悉 Python，PostgreSQL 优先。",
        "硕士学历；有3年以上 FastAPI 开发经验。",
        "每周实习4天，至少3个月；熟悉 LangGraph。",
        "English required, Python experience preferred.",
        "不要求 Java 经验，熟悉 JavaScript。",
        "使用 RAG 和 MCP，有真实项目优先。",
        "Linux 基础；Docker 优先；不需要 Redis。",
        "掌握 MySQL，熟悉 Git 与 CI/CD。",
        "大专以上，能全职到岗；熟悉 pgvector。",
        "Postgres 数据库经验优先。",
    ],
)
def test_ten_synthetic_jds_keep_exact_citations_and_no_qualification_claim(jd):
    profile = validate_profile(
        {"skills": [{"name": "Python", "evidence": "项目真实实现", "reference": "README"}]}
    )
    result = rules_analysis(jd, profile, taxonomy())
    assert result["quality_verified"] is False
    for item in [*result["requirements"], *result["hard_conditions"]]:
        assert jd[item["start"] : item["end"]] == item["quote"]
    assert all(
        item["assessment"] in {"evidence_supplied", "declared_only", "not_in_profile"}
        for item in result["requirements"]
    )


def test_hard_condition_headers_are_not_requirements_and_at_least_years_are_detected():
    profile = validate_profile({"title": "验收用空资料"})
    header = rules_analysis("学历及经验\n技术要求\n1. 掌握 Python。", profile, taxonomy())
    assert [row["category"] for row in header["hard_conditions"]] == []
    years = rules_analysis("学历及经验\n2. 具备至少2年Python开发实战经验。", profile, taxonomy())
    assert [row["category"] for row in years["hard_conditions"]].count("experience") == 1
    assert "至少2年Python开发实战经验" in years["hard_conditions"][0]["quote"]


def test_familiar_and_mastery_are_required_but_plus_is_preferred():
    profile = validate_profile({"title": "验收用空资料"})
    result = rules_analysis("熟悉 Python；熟悉 Redis 者优先。", profile, taxonomy())
    values = {row["name"]: row["priority"] for row in result["requirements"]}
    assert values["Python"] == "required" and values["Redis"] == "preferred"


def test_react_framework_is_not_reasoning_framework():
    profile = validate_profile({"title": "验收用空资料"})
    reasoning = rules_analysis("理解 ReAct 与 CoT。", profile, taxonomy())
    assert "React" not in {row["name"] for row in reasoning["requirements"]}
    assert "ReAct" in {row["name"] for row in reasoning["requirements"]}
    frontend = rules_analysis("熟悉 React 与 Vue。", profile, taxonomy())
    assert "React" in {row["name"] for row in frontend["requirements"]}


def test_word_boundaries_negation_and_evidence_not_keyword_absence():
    profile = validate_profile(
        {
            "skills": [
                {"name": "Python"},
                {"name": "FastAPI", "evidence": "真实接口实现", "reference": "项目文档"},
            ]
        }
    )
    result = rules_analysis(
        "只使用 JavaScript。不需要 Redis。Python 与 FastAPI 开发。", profile, taxonomy()
    )
    values = {row["name"]: row for row in result["requirements"]}
    assert "Java" not in values and "JavaScript" in values
    assert values["Redis"]["priority"] == "not_required"
    assert values["Python"]["assessment"] == "declared_only"
    assert values["FastAPI"]["assessment"] == "evidence_supplied"
    long = rules_analysis("背景说明" * 800 + "熟悉 Python。", profile, taxonomy())
    assert "Python" in long["requirements"][0]["quote"]


@pytest.mark.parametrize(
    "bad",
    [
        {"api_key": "never"},
        {"skills": [{"name": "Python"}, {"name": "python"}]},
        {"facts": [{"category": [], "value": "本科"}]},
        {"skills": ["Python"]},
    ],
)
def test_profile_rejects_credentials_unknown_fields_and_ambiguous_values(bad):
    with pytest.raises(DomainError):
        validate_profile(bad)


def test_model_cannot_invent_citations_or_personal_evidence():
    profile = validate_profile({})
    for raw in [
        {"requirements": [{"name": "Python", "quote": "不存在的原文"}], "hard_conditions": []},
        {
            "requirements": [{"name": "Python", "quote": "Python", "assessment": "qualified"}],
            "hard_conditions": [],
        },
        {"requirements": [], "hard_conditions": [{"category": [], "quote": "本科"}]},
    ]:
        with pytest.raises(DomainError):
            model_analysis("本科，Python", profile, taxonomy(), raw)
    safe = model_analysis(
        "本科，Python", profile, taxonomy(), {"requirements": [], "hard_conditions": []}
    )
    assert safe["requirements"] and safe["hard_conditions"]  # omissions cannot weaken rules.


def test_private_json_cas_duplicate_keys_corruption_and_legacy(tmp_path):
    file = PrivateJson(tmp_path / "profile.json", allow_plain=True)
    first = file.save({"title": "原资料", "skills": [], "facts": []}, "missing")
    with pytest.raises(VersionConflict):
        file.save({"title": "不能覆盖"}, "missing")
    assert file.read() == first
    file.path.write_text('{"skills": [], "skills": ["wrong"]}', encoding="utf-8")
    pristine = file.path.read_bytes()
    with pytest.raises(StorageError):
        file.save({"title": "不清空"}, first["revision"])
    assert file.path.read_bytes() == pristine
    file.path.write_text('{"skills": [], "facts": []}', encoding="utf-8")
    legacy = file.read()
    assert legacy["revision"].startswith("legacy-")
    file.save(validate_profile(legacy["data"]), legacy["revision"])
    assert not file.read()["revision"].startswith("legacy-")


@contextmanager
def model_fixture(answer=None, status=200):
    received = []
    answer = (
        answer
        if answer is not None
        else {"requirements": [{"name": "Python", "quote": "熟悉 Python"}], "hard_conditions": []}
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(status)
            if status == 302:
                self.send_header(
                    "Location", f"http://127.0.0.1:{self.server.server_port}/redirected"
                )
            self.end_headers()
            response = (
                {
                    "choices": [{"message": {"content": json.dumps(answer)}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                }
                if status == 200
                else {"error": "fixture-token private upstream body"}
            )
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def api(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    store = RecordStore("qa_insights_" + uuid4().hex[:10])
    with TestClient(create_app(store, tmp_path, token="")) as client:
        yield client, tmp_path
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


def lead(client):
    return client.post(
        "/api/jobs/leads",
        json={
            "data": {
                "title": "后端",
                "company": "示例公司",
                "jd_text": "本科及以上；熟悉 Python；PostgreSQL 优先。",
            }
        },
    ).json()


def configure(client, base):
    connection = client.app.state.search.connection
    connection.save(
        {
            "revision": connection.load()["revision"],
            "api_key": "fixture-token",
            "base_url": base,
            "model": "mock-protocol-model",
        }
    )


def test_profile_rule_analysis_stale_sources_and_confirmed_gap_cards(api):
    client, root = api
    job = lead(client)
    profile = client.get("/api/jobs/profile").json()
    assert profile["revision"] == "missing" and not (root / "data/local/job-profile.json").exists()
    new = client.put(
        "/api/jobs/profile",
        json={
            "revision": profile["revision"],
            "data": {
                "skills": [{"name": "Python", "evidence": "真实项目接口", "reference": "README"}]
            },
        },
    )
    assert new.status_code == 200
    profile = new.json()
    assert (
        client.put("/api/jobs/profile", json={"revision": "missing", "data": {}}).status_code == 409
    )
    assert not client.get(f"/api/jobs/leads/{job['id']}/gap").json()["persisted"]
    body = {"version": 1, "profile_revision": profile["revision"], "mode": "rules"}
    result = client.post(f"/api/jobs/leads/{job['id']}/analyze", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["analysis"]["mode"] == "rules"
    assert not client.get(f"/api/jobs/leads/{job['id']}/gap").json()["stale"]
    path = f"/api/jobs/leads/{job['id']}/learning-cards"
    cards = {
        "version": 1,
        "profile_revision": profile["revision"],
        "names": ["PostgreSQL"],
        "confirmation": "确认创建复习卡",
    }
    assert client.post(path, json={**cards, "confirmation": ""}).status_code == 400
    assert len(client.post(path, json=cards).json()["created"]) == 1
    assert len(client.post(path, json=cards).json()["reused"]) == 1
    assert client.post(path, json={**cards, "names": ["Python"]}).status_code == 400
    client.put("/api/jobs/profile", json={"revision": profile["revision"], "data": {"skills": []}})
    assert client.get(f"/api/jobs/leads/{job['id']}/gap").json()["stale"]
    assert client.post(path, json=cards).status_code == 409
    assert all(
        row["kind"] not in {"job_profile", "job_analysis"}
        for row in client.get("/api/export").json()["records"]
    )


def test_model_requires_confirmation_then_calls_once_and_bounds_untrusted_output(api):
    client, _ = api
    job = lead(client)
    profile = client.get("/api/jobs/profile").json()
    body = {"version": 1, "profile_revision": profile["revision"], "mode": "model"}
    path = f"/api/jobs/leads/{job['id']}/analyze"
    with model_fixture() as (base, received):
        configure(client, base)
        assert client.post(path, json=body).status_code == 400 and not received
        body["confirmation"] = "发送岗位与资料进行分析"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: client.post(path, json=body), range(2)))
        assert all(response.status_code == 200 for response in results)
        assert len(received) == 1 and results[0].json()["analysis"]["mode"] == "model"
        assert results[0].json()["analysis"]["hard_conditions"]
        assert "fixture-token" not in json.dumps(results[0].json())
        assert results[0].json()["model_metadata"]["usage"]["prompt_tokens"] == 12
        assert results[0].json()["model_metadata"]["cost"] == "unknown"
    with model_fixture(
        {"requirements": [{"name": "Python", "quote": "编造原文"}], "hard_conditions": []}
    ) as (base, received):
        configure(client, base)
        result = client.post(path, json={**body, "request_id": uuid4().hex}).json()
        assert result["status"] == "fallback" and result["analysis"]["mode"] == "rules"


@pytest.mark.parametrize("status", [503, 302])
def test_model_failure_degrades_without_supplier_body_or_auto_retry(api, status):
    client, _ = api
    job = lead(client)
    profile = client.get("/api/jobs/profile").json()
    with model_fixture(status=status) as (base, received):
        configure(client, base)
        body = {
            "version": 1,
            "profile_revision": profile["revision"],
            "mode": "model",
            "confirmation": "发送岗位与资料进行分析",
        }
        path = f"/api/jobs/leads/{job['id']}/analyze"
        first, repeated = client.post(path, json=body), client.post(path, json=body)
        assert first.status_code == repeated.status_code == 200
        assert first.json()["status"] == "fallback" and repeated.json()["reused"]
        assert (
            len(received) == 1
            and "private upstream body" not in first.text
            and "fixture-token" not in first.text
        )
