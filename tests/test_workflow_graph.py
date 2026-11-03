"""DAG workflow contract: cycles, reachability, node fields and template paths."""

import pytest

from rag_tech_retriever.domains.automation import validate_workflow
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.workflow_graph import resolve, validate_graph_workflow


def graph(**overrides):
    base = {
        "title": "测试 DAG",
        "kind": "graph",
        "nodes": [
            {"id": "input", "type": "input"},
            {"id": "search", "type": "tool", "tool_id": "web_search", "agent_id": "agent-a",
             "arguments": {"query": "{{input.query}}"}},
            {"id": "merge", "type": "merge"},
        ],
        "edges": [["input", "search"], ["search", "merge"]],
    }
    base.update(overrides)
    return base


def test_valid_graph_is_normalized_and_dispatched():
    data = validate_workflow(graph())
    assert data["kind"] == "graph"
    assert [node["id"] for node in data["nodes"]] == ["input", "search", "merge"]
    assert data["edges"] == [["input", "search"], ["search", "merge"]]
    assert data["max_retries"] == 1 and data["node_timeout_seconds"] == 60


@pytest.mark.parametrize("overrides", [
    {"nodes": [{"id": "input", "type": "input"}]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "input", "type": "merge"}],
     "edges": [["input", "input"]]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "x", "type": "merge"}],
     "edges": [["x", "input"]]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "x", "type": "merge"},
               {"id": "y", "type": "merge"}], "edges": [["input", "x"]]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "x", "type": "unknown"}],
     "edges": [["input", "x"]]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "x", "type": "tool"}],
     "edges": [["input", "x"]]},
    {"nodes": [{"id": "input", "type": "input"}, {"id": "x", "type": "approval"}],
     "edges": [["input", "x"]]},
])
def test_invalid_graphs_are_rejected(overrides):
    with pytest.raises(DomainError):
        validate_graph_workflow(graph(**overrides))


def test_cycle_is_rejected_even_when_every_node_is_reachable():
    nodes = [{"id": "input", "type": "input"}, {"id": "a", "type": "merge"}, {"id": "b", "type": "merge"}]
    with pytest.raises(DomainError, match="有环"):
        validate_graph_workflow(graph(nodes=nodes, edges=[["input", "a"], ["a", "b"], ["b", "a"]]))


def test_template_resolution_is_strict():
    context = {"input": {"query": "RAG"}, "nodes": {"a": {"answer": "结论"}}}
    assert resolve("{{input.query}}", context) == "RAG"
    assert resolve("搜索：{{nodes.a.answer}}", context) == "搜索：结论"
    assert resolve({"q": ["{{input.query}}"]}, context) == {"q": ["RAG"]}
    with pytest.raises(DomainError, match="不存在"):
        resolve("{{nodes.missing.answer}}", context)
    with pytest.raises(DomainError, match="只允许"):
        resolve("{{secret.token}}", context)
