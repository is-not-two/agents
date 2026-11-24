"""自动编排：任意 Agent 数组过校验、草稿可修订、保存时才落库。"""

import json
from typing import ClassVar

import pytest

from rag_tech_retriever.common.provider import ProviderError
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.workflow_composer import WorkflowComposer


class _Caps:
    class http:
        tools: ClassVar[dict] = {}

    def code_roots(self) -> list:
        return [{"name": "demo", "title": "演示仓库", "writable": True}]

    def validate_binding(self, profile: dict) -> dict:
        for name in profile.get("tool_ids", []):
            if name not in {"knowledge_search", "web_search"}:
                raise DomainError("Agent包含不存在的工具或未绑定MCP服务")
        root = profile.get("workspace", {}).get("root", "")
        if root and root != "demo":
            raise DomainError("代码工作区未登记")
        return profile


class _Store:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def save(self, kind: str, data: dict, *args) -> dict:
        row = {"id": f"{kind}-{len(self.rows)}", "kind": kind, "version": 1, "data": data}
        self.rows.append(row)
        return row


def build(mode="rules", post=None, template="generic"):
    return WorkflowComposer(_Store(), _Caps()).build_draft("做一个求职工作台", mode, post=post,
                                                           template=template)


def test_rules_draft_uses_two_agents_and_real_placeholders() -> None:
    draft = build()
    assert [item["key"] for item in draft["agents"]] == ["planner", "producer"]
    assert [node["id"] for node in draft["workflow"]["nodes"]] == [
        "input", "plan", "produce", "merge"]
    assert draft["mapping"] == {"plan": "planner", "produce": "producer"}
    queries = [node.get("query", "") for node in draft["workflow"]["nodes"]]
    assert "{{nodes.plan.answer}}" in queries[2]
    assert all("output" not in query for query in queries)


def test_code_template_requires_a_writable_root() -> None:
    draft = build(template="code")
    assert [item["key"] for item in draft["agents"]] == ["planner", "coder", "reviewer"]
    assert draft["agents"][1]["profile"]["workspace"]["root"] == "demo"
    assert [node["id"] for node in draft["workflow"]["nodes"]] == [
        "input", "plan", "code", "review", "merge"]

    class _None(_Caps):
        def code_roots(self) -> list:
            return []

    fallback = WorkflowComposer(_Store(), _None()).build_draft("目标", "rules", template="code")
    assert [item["key"] for item in fallback["agents"]] == ["planner", "producer"]


def test_model_mode_fails_closed_without_provider() -> None:
    with pytest.raises(ProviderError):
        build("model")


def test_unknown_mode_and_template_are_rejected() -> None:
    with pytest.raises(DomainError):
        build("magic")
    with pytest.raises(DomainError):
        build("rules", template="magic")


def test_catalog_only_lists_registered_tools() -> None:
    catalog = WorkflowComposer(_Store(), _Caps()).catalog()
    assert "knowledge_search" in catalog
    assert "not_a_tool" not in catalog


class _Conn:
    def load(self) -> dict:
        return {"api_key": "test-key", "base_url": "https://example.invalid",
                "model": "test-model", "revision": "test"}


def _transport(payload):
    def post(config, body, timeout, max_chars):
        _transport.seen = body
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return {"choices": [{"message": {"content": content}}]}
    return post


VALID_OUTPUT = {
    "agents": [
        {"key": "planner", "title": "规划", "system_prompt": "拆解任务",
         "tools": ["knowledge_search"]},
        {"key": "coder", "title": "实现", "system_prompt": "改代码",
         "workspace": {"root": "demo", "write": "each"}},
    ],
    "workflow": {
        "title": "模型生成的流程",
        "nodes": [
            {"id": "input", "type": "input"},
            {"id": "plan", "type": "agent", "agent": "planner", "query": "拆解"},
            {"id": "code", "type": "agent", "agent": "coder", "query": "实施 {{nodes.plan.answer}}"},
            {"id": "merge", "type": "merge"},
        ],
        "edges": [["input", "plan"], ["plan", "code"], ["code", "merge"]],
    },
}


def model_draft(payload=None, template="generic"):
    composer = WorkflowComposer(_Store(), _Caps(), _Conn())
    return composer, composer.build_draft("做一个工作台", "model",
                                          post=_transport(payload or VALID_OUTPUT),
                                          template=template)


def test_model_mode_produces_arbitrary_agents_not_fixed_roles() -> None:
    _composer, draft = model_draft()
    assert [item["key"] for item in draft["agents"]] == ["planner", "coder"]
    assert draft["agents"][1]["profile"]["workspace"] == {"root": "demo", "write": "each",
                                                          "shell": False}
    assert draft["mapping"] == {"plan": "planner", "code": "coder"}
    system = _transport.seen["messages"][0]["content"]
    assert "knowledge_search" in system and "demo" in system
    assert "{{nodes.<节点id>.answer}}" in system


@pytest.mark.parametrize("patch", [
    {"agents": [{"key": "x", "tools": ["evil_tool"]}]},
    {"agents": [{"key": "x", "tools": ["code_write"]}]},
    {"agents": [{"key": "x", "workspace": {"root": "/etc"}}]},
    {"agents": [{"key": "x"}, {"key": "x"}]},
    {"agents": []},
])
def test_model_mode_rejects_unregistered_capabilities(patch) -> None:
    payload = {**VALID_OUTPUT, **patch}
    with pytest.raises(DomainError):
        model_draft(payload)


def test_model_mode_rejects_unknown_agent_reference_and_cycles() -> None:
    payload = {"agents": VALID_OUTPUT["agents"], "workflow": {
        "title": "坏流程", "nodes": [
            {"id": "input", "type": "input"},
            {"id": "a", "type": "agent", "agent": "ghost", "query": "A"},
            {"id": "merge", "type": "merge"}],
        "edges": [["input", "a"], ["a", "merge"]]}}
    with pytest.raises(DomainError):
        model_draft(payload)
    cyclic = {"agents": VALID_OUTPUT["agents"], "workflow": {
        "title": "环", "nodes": [
            {"id": "input", "type": "input"},
            {"id": "a", "type": "agent", "agent": "planner", "query": "A"},
            {"id": "b", "type": "agent", "agent": "coder", "query": "B"}],
        "edges": [["input", "a"], ["a", "b"], ["b", "a"]]}}
    with pytest.raises(DomainError):
        model_draft(cyclic)


def test_model_mode_rejects_invalid_json() -> None:
    with pytest.raises(DomainError):
        model_draft("not json")


def test_save_replaces_draft_references_with_real_ids() -> None:
    store = _Store()
    composer = WorkflowComposer(store, _Caps())
    draft = composer.build_draft("目标")
    result = composer.save(draft)
    workflows = [row for row in store.rows if row["kind"] == "workflow"]
    saved = {row["id"] for row in store.rows if row["kind"] == "agent_profile"}
    assert len(workflows) == 1 and len(saved) == 2
    assert result["workflow_id"] == workflows[0]["id"]
    assert {item["key"] for item in result["agents"]} == {"planner", "producer"}
    for node in workflows[0]["data"]["nodes"]:
        if node["type"] == "agent":
            assert node["agent_id"] in saved


def test_save_revalidates_client_draft_and_refuses_forged_grants() -> None:
    composer = WorkflowComposer(_Store(), _Caps())
    draft = composer.build_draft("目标")
    forged = json.loads(json.dumps(draft))
    forged["agents"][0]["profile"]["tool_ids"] = ["http://evil.example"]
    with pytest.raises(DomainError):
        composer.save(forged)
    broken = json.loads(json.dumps(draft))
    broken["mapping"] = {}
    with pytest.raises(DomainError):
        composer.save(broken)


def test_revise_returns_new_draft_and_structural_diff() -> None:
    composer = WorkflowComposer(_Store(), _Caps(), _Conn())
    draft = composer.build_draft("目标")
    revised = {**VALID_OUTPUT, "workflow": {
        "title": "修订后的流程",
        "nodes": [
            {"id": "input", "type": "input"},
            {"id": "plan", "type": "agent", "agent": "planner", "query": "拆解"},
            {"id": "code", "type": "agent", "agent": "coder", "query": "实施"},
            {"id": "test", "type": "approval", "message": "确认上线"},
            {"id": "merge", "type": "merge"},
        ],
        "edges": [["input", "plan"], ["plan", "code"], ["code", "test"], ["test", "merge"]],
    }}
    result = composer.revise(draft, "加一个上线确认", post=_transport(revised))
    assert result["draft"]["workflow"]["title"] == "修订后的流程"
    changes = result["changes"]
    assert changes["nodes_added"] == ["code", "test"]
    assert changes["nodes_removed"] == ["produce"]
    assert ["code", "test"] in changes["edges_added"]
    assert ["produce", "merge"] in changes["edges_removed"]
    assert changes["agents_added"] == ["coder"]
    assert changes["agents_removed"] == ["producer"]
    assert changes["title"]["after"] == "修订后的流程"


def test_revise_requires_feedback_and_provider() -> None:
    composer = WorkflowComposer(_Store(), _Caps())
    draft = composer.build_draft("目标")
    with pytest.raises(DomainError):
        composer.revise(draft, "   ")
    with pytest.raises(ProviderError):
        composer.revise(draft, "改一下")


def test_diff_reports_unchanged_draft_as_empty() -> None:
    composer = WorkflowComposer(_Store(), _Caps())
    draft = composer.build_draft("目标")
    changes = composer.diff(draft, composer.build_draft("目标"))
    assert not any(changes[key] for key in ("nodes_added", "nodes_removed", "nodes_changed",
                                            "edges_added", "edges_removed", "agents_changed"))
