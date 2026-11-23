"""Backup compatibility for records written by the team and coding-loop services."""

from copy import deepcopy

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.snapshot import preview_restore, validate_snapshot

TEAM = {
    "kind": "team", "status": "completed", "title": "团队任务",
    "input": {"task": "核对记录"}, "turns": [{"author": "worker", "text": "完成"}],
    "speakers": ["worker"], "result": {"answer": "结论", "notes": []},
}
LOOP = {
    "kind": "loop", "status": "failed", "title": "编码任务",
    "input": {"task": "检查构建", "gate": "pytest", "repo": "/fixture/repo"},
    "summary": {"status": "budget", "attempts": [{"round": 1, "passed": False}], "diff": ""},
}


def snapshot(*items: dict) -> dict:
    """Build format-1 records without fake workflow IDs or step lists."""
    return {"format_version": 1, "records": [
        {"id": f"fixture-{i}", "kind": "workflow_run", "data": data, "deleted": i == 2}
        for i, data in enumerate(items)
    ]}


def test_terminal_history_roundtrips_without_changing_payload():
    source = snapshot(TEAM, LOOP, {**LOOP, "status": "completed"})
    validated = validate_snapshot(source)
    assert validated == source
    assert preview_restore(source, validated)["change_count"] == 0
    validated["records"][0]["data"]["turns"][0]["text"] = "changed"
    assert source["records"][0]["data"]["turns"][0]["text"] == "完成"


@pytest.mark.parametrize("record", [TEAM, LOOP])
@pytest.mark.parametrize("status", ["running", "awaiting_confirmation", "confirmed"])
def test_rejects_nonterminal_runtime_state(record, status):
    with pytest.raises(DomainError, match="只允许已结束"):
        validate_snapshot(snapshot({**record, "status": status}))


@pytest.mark.parametrize(("record", "change"), [
    (TEAM, {"turns": [7]}), (TEAM, {"result": []}),
    (LOOP, {"summary": []}), (LOOP, {"summary": {"attempts": [None]}}),
    (LOOP, {"pending_calls": [{"name": "write"}]}),
])
def test_rejects_malformed_or_replayable_records(record, change):
    with pytest.raises(DomainError):
        validate_snapshot(snapshot({**deepcopy(record), **change}))


@pytest.mark.parametrize(("source", "prefix"), [("interview", "learn-"), ("jd_gap", "learn-jd-")])
def test_generated_learning_card_retains_missing_source_without_recreating_it(source, prefix):
    key = "a" * 64
    card = {"kind": "learning_card", "id": prefix + key, "deleted": False, "data": {
        "title": "合成卡片", "source": source, "source_id": "original", "source_version": 2,
        "source_key": key, "due_at": "2026-11-11T00:00:00+00:00",
    }}
    data = {"format_version": 1, "records": [card]}
    checked = validate_snapshot(data)
    assert len(checked["records"]) == 1
    assert checked["records"][0]["data"]["source_id"] == "original"
    assert preview_restore(checked, checked)["missing_learning_sources"] == 1
    with pytest.raises(DomainError, match="来源记录缺失或类型不匹配"):
        validate_snapshot({**data, "records": [{**card, "id": "wrong"}]})
    with pytest.raises(DomainError, match="来源记录缺失或类型不匹配"):
        validate_snapshot({**data, "records": [card, {
            "kind": "knowledge", "id": "original", "data": {"title": "错类型", "content": "合成正文"},
        }]})
