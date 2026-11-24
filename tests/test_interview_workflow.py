"""Exercise the same HTTP routes the Web uses, without live data or a provider."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_tech_retriever.agent import capability_runtime
from rag_tech_retriever.api.routes.automation import create_router
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.workflow_graph import resolve
from rag_tech_retriever.platform.agent_capabilities import CapabilityService
from rag_tech_retriever.platform.interview_workflow import evidence_output
from rag_tech_retriever.platform.record_store import WORKSPACE_KINDS, RecordMissing
from rag_tech_retriever.platform.resume_service import ResumeService
from rag_tech_retriever.platform.workflow_composer import WorkflowComposer


class Store:
    def __init__(self):
        self.rows = {}

    def save(self, kind, data, record_id=None, version=None):
        record_id = record_id or f"{kind}-{len(self.rows)}"
        if version:
            assert self.rows[record_id]["version"] == version
        row = {"id": record_id, "kind": kind, "version": (version or 0) + 1,
               "deleted": False, "data": deepcopy(data)}
        self.rows[record_id] = row
        return deepcopy(row)

    def get(self, record_id):
        if record_id not in self.rows:
            raise RecordMissing("记录不存在")
        return deepcopy(self.rows[record_id])

    def list(self, kind, *, limit, data_kinds, omit):
        rows = [deepcopy(row) for row in self.rows.values()
                if row["kind"] == kind and row["data"].get("kind") in data_kinds]
        for row in rows:
            for key in omit:
                row["data"].pop(key, None)
        return rows[-limit:]


@pytest.fixture
def interview(tmp_path, monkeypatch):
    store = Store()
    lead = store.save("job_lead", {"title": "后端工程师", "jd_text": "排查 PostgreSQL 慢查询"})
    resume = ResumeService(store, tmp_path).upload(
        "test.txt", "项目经历\n维护过一个 Python 接口。".encode(), "原简历")
    note = store.save("knowledge", {"title": "证据", "content": "私有证据：检查过执行计划。"})
    store.save("knowledge", {"title": "其他", "content": "绝不可读的未选中资料"})
    connection = SimpleNamespace(load=lambda: {
        "api_key": "fixture", "base_url": "https://example.invalid", "model": "fixture",
    })
    search = SimpleNamespace(connection=connection)
    caps = CapabilityService(tmp_path, store, search, lambda *_: None)
    runtime = capability_runtime.AgentRuntime(store, connection, caps)
    messages = []
    def grounded(*facts, pending=(), suggestions=()):
        return json.dumps({"facts": facts, "pending": pending, "suggestions": suggestions})

    replies = iter([grounded("维护过一个 Python 接口。"), "你具体排查了什么？",
                    grounded("私有证据：检查过执行计划。"), "检查执行计划后怎么确认改善？",
                    grounded(pending=["材料无证据，不能声称有改善。"]),
                    grounded("私有证据：检查过执行计划。", suggestions=["补充可核验结果。"])])

    def post(_config, body, *_args):
        messages.append(deepcopy(body))
        return {"choices": [{"message": {"content": next(replies)}}]}

    monkeypatch.setattr(capability_runtime, "post_chat", post)
    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(store=store, search=search,
                                                     capabilities=caps, runtime=runtime)))
    client = TestClient(app)
    draft = client.post("/api/automation/compose/draft", json={
        "goal": "三角色模拟", "template": "interview",
    })
    assert draft.status_code == 201, draft.text
    assert not any(row["kind"] == "agent_profile" for row in store.rows.values())
    saved = client.post("/api/automation/compose/save", json={"draft": draft.json()})
    assert saved.status_code == 201, saved.text
    flow = saved.json()
    inputs = {"lead_id": lead["id"], "resume_id": resume["id"], "knowledge_id": note["id"]}
    return SimpleNamespace(client=client, inputs=inputs, store=store, flow=flow, draft=draft.json(),
                           messages=messages, resume=store.get(resume["id"]), connection=connection,
                           caps=caps)


def run(interview):
    response = interview.client.post(f"/api/workflows/{interview.flow['workflow_id']}/run", json={
        "version": interview.flow["version"], "input": interview.inputs,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_interview_handoffs_privacy_and_no_business_write(interview):
    row = run(interview)
    assert row["kind"] not in WORKSPACE_KINDS
    assert row["data"]["status"] == "completed", row["data"]["result"]
    outputs = row["data"]["node_outputs"]
    assert "材料无证据" in outputs["followup_answer"]["answer"]
    assert row["data"]["interview_lead_id"] == interview.inputs["lead_id"]
    assert row["data"]["result"]["answer"] == outputs["boss_review"]["answer"]
    messages = [body["messages"][-1]["content"] for body in interview.messages]
    assert len(messages) == 6
    assert "检查过执行计划。" in messages[3]
    assert outputs["followup_question"]["answer"] in messages[4]
    assert "不能声称有改善" not in messages[5]  # Pending text must not become model evidence.
    assert all("【选中知识】" in messages[i] for i in (0, 2, 4))
    assert all("【选中知识】" not in messages[i] for i in (1, 3, 5))
    assert not any("绝不可读" in message for message in messages)
    assert all(not body.get("tools") for body in interview.messages)
    children = [interview.store.get(item["run_id"]) for item in outputs.values() if "run_id" in item]
    assert len(children) == 6 and all(child["kind"] not in WORKSPACE_KINDS for child in children)
    assert [x["key"] for x in interview.flow["agents"]] == ["candidate", "interviewer", "boss_agent"]
    assert interview.store.get(interview.resume["id"]) == interview.resume
    assert not any(item["kind"] in {"interview_report", "interview_prep", "application"}
                   for item in interview.store.rows.values())
    assert interview.client.get(f"/api/workflow-runs/{row['id']}").status_code == 200


def test_interview_without_model_stops_at_resume_draft(interview):
    interview.connection.load = dict
    result = run(interview)["data"]
    assert result["status"] == "failed"
    assert result["node_status"]["resume_draft"] == "failed"
    assert "尚未配置模型" in result["result"]["notes"][0]
    assert "first_question" not in result["node_outputs"]
    assert not interview.messages


def test_interview_rejects_wrong_record_kind(interview):
    interview.inputs["knowledge_id"] = interview.resume["id"]
    result = run(interview)["data"]
    assert result["status"] == "failed"
    assert result["node_status"]["material"] == "failed"
    assert not interview.messages


def test_interview_accepts_english_source_sentences_without_accepting_fragments():
    material = {"resume_text": "Worked with Dr. Chen. No production claims. Used PostgreSQL 16.2 in a lab.",
                "knowledge": ""}
    def output(fact):
        return evidence_output(json.dumps({"facts": [fact], "pending": [], "suggestions": []}),
                               material, {}, "resume_draft")

    for fact in ("Worked with Dr. Chen.", "No production claims.", "Used PostgreSQL 16.2 in a lab."):
        assert output(fact)["verified"] == fact
    for fragment in ("Worked with Dr.", "production claims.", "Used PostgreSQL 16."):
        with pytest.raises(DomainError, match="无法逐字核对"):
            output(fragment)


def test_interview_ai_revision_cannot_expand_permissions_or_replace_graph(interview):
    composer = WorkflowComposer(interview.store, interview.caps, interview.connection)
    raw = {"agents": [{"key": "interviewer", "system_prompt": "优先追问排障。",
                       "tools": ["knowledge_search"], "scopes": ["personal"]}],
           "workflow": {"nodes": []}}

    def post(*_args, **_kwargs):
        return {"choices": [{"message": {"content": json.dumps(raw)}}]}

    revised = composer.revise(interview.draft, "让面试官优先追问排障", post=post)["draft"]
    profile = revised["agents"][1]["profile"]
    assert "优先追问排障" in profile["system_prompt"]
    assert profile["tool_ids"] == [] and profile["scopes"] == ["docs"]
    assert revised["workflow"] == interview.draft["workflow"]
    assert revised["mapping"] == interview.draft["mapping"]


def test_interview_source_cannot_be_rebound_to_another_knowledge_id(interview):
    row = interview.store.get(interview.flow["workflow_id"])
    node = next(node for node in row["data"]["nodes"] if node["id"] == "material")
    node["arguments"]["knowledge_id"] = "knowledge-3"
    updated = interview.client.put(f"/api/workflows/{row['id']}", json={
        "version": row["version"], "data": row["data"],
    })
    assert updated.status_code == 200, updated.text
    interview.flow["version"] = updated.json()["version"]
    result = run(interview)["data"]
    assert result["node_status"]["material"] == "failed"
    assert "本次运行选中" in result["result"]["notes"][0]
    assert not interview.messages


def test_workflow_never_expands_placeholders_inside_source_text():
    context = {"input": {"raw": "{{input.knowledge}}", "knowledge": "所选内容"}}
    assert resolve("简历：{{input.raw}}，知识：{{input.knowledge}}", context) == (
        "简历：{{input.knowledge}}，知识：所选内容")


def test_evidence_rejects_invented_or_partial_assertions():
    material = {"resume_text": "仅维护既有测试，未开发接口。观察到 Pod Ready。", "knowledge": ""}
    for invalid in ("开发接口。", "使用 kubectl wait 验证。", "维护既有测试"):
        with pytest.raises(DomainError, match="阻止"):
            evidence_output(json.dumps({"facts": [invalid], "pending": [], "suggestions": []}),
                            material, {}, "resume_draft")
    item = evidence_output(json.dumps({"facts": ["观察到 Pod Ready。"], "pending": ["使用了什么命令？"],
                                       "suggestions": ["下次记录命令。"]}), material, {}, "resume_draft")
    assert item["verified"] == "观察到 Pod Ready。"
    with pytest.raises(DomainError, match="阻止"):
        evidence_output(json.dumps({"facts": ["仅维护既有测试，未开发接口。"], "pending": [], "suggestions": []}),
                        material, {"resume_draft": item}, "boss_review")


def test_legacy_interview_history_associates_lead_without_leaking_inputs(interview):
    row = interview.store.save("agent_session", {"kind": "graph", "private_interview": True,
        "input": {"lead_id": interview.inputs["lead_id"], "resume_id": "legacy-private"},
        "node_outputs": {"resume_draft": {"answer": "旧版草稿"}}})
    result = interview.client.get("/api/workflow-runs").raise_for_status().json()
    summary = next(item["data"] for item in result if item["id"] == row["id"])
    assert summary["interview_lead_id"] == interview.inputs["lead_id"]
    assert "input" not in summary and "node_outputs" not in summary
    detail = interview.client.get(f"/api/workflow-runs/{row['id']}").raise_for_status().json()
    assert detail["data"]["node_outputs"]["resume_draft"]["answer"] == "旧版草稿"
