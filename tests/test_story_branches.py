"""Main forks and side descendants survive validation without prerequisite coupling."""

import pytest

from rag_tech_retriever.domains.life_planning import DomainError, validate_plan


def story(nodes: list[dict]) -> dict:
    """Build a small compatible planning record."""
    return {"title": "主线 1", "acts": [{"id": "act", "title": "树", "nodes": nodes}]}


def test_main_forks_and_legacy_nodes() -> None:
    nodes = [
        {"id": "two", "title": "2", "kind": "main"},
        {"id": "three", "title": "3", "kind": "main", "parent_id": "two"},
        {"id": "four", "title": "4", "kind": "main", "parent_id": "two"},
        {"id": "five", "title": "5", "kind": "main", "parent_id": "three"},
        {"id": "legacy", "title": "旧任务", "parent_id": "two"},
    ]
    clean = validate_plan(story(nodes))
    assert clean["acts"][0]["nodes"][-1]["kind"] == "side"
    assert all(not n["requires"] for n in clean["acts"][0]["nodes"])
    assert validate_plan(clean) == clean


def test_root_completion_is_independent_and_typed() -> None:
    data = story([{"id": "child", "title": "未完成子任务"}])
    assert validate_plan(data)["done"] is False
    data["done"] = True
    clean = validate_plan(data)
    assert clean["done"] is True
    assert clean["acts"][0]["nodes"][0]["done"] is False
    data["done"] = "true"
    with pytest.raises(DomainError, match="布尔"):
        validate_plan(data)


@pytest.mark.parametrize("kind", [[], "other", None])
def test_reject_bad_branch_kind(kind: object) -> None:
    with pytest.raises(DomainError):
        validate_plan(story([{"id": "x", "title": "x", "kind": kind}]))


def test_reject_main_under_side_and_cycle() -> None:
    with pytest.raises(DomainError, match="主线"):
        validate_plan(story([
            {"id": "a", "title": "支线"},
            {"id": "b", "title": "主线", "kind": "main", "parent_id": "a"},
        ]))
    with pytest.raises(DomainError, match="循环"):
        validate_plan(story([
            {"id": "a", "title": "a", "kind": "main", "parent_id": "b"},
            {"id": "b", "title": "b", "kind": "main", "parent_id": "a"},
        ]))
