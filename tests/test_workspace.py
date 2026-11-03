"""真实 PostgreSQL 持久化、并发版本保护、规划反例与历史恢复。"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from rag_tech_retriever.domains.life_planning import DomainError, derive_plan, validate_plan
from rag_tech_retriever.platform.record_store import RecordStore, VersionConflict


@pytest.fixture
def store():
    """唯一前缀表隔离生产；完成后只删除本测试的两张表。"""
    storage = RecordStore("qa_" + uuid4().hex[:12])
    storage.ensure_schema()
    try:
        yield storage
    finally:
        with storage.transaction() as cursor:
            cursor.execute(f"DROP TABLE {storage.versions}")
            cursor.execute(f"DROP TABLE {storage.records}")


def sample_plan() -> dict:
    """两节点依赖链，便于验证解锁条件。"""
    return {
        "title": "个人规划",
        "kind": "main",
        "acts": [
            {
                "id": "act",
                "title": "第一阶段",
                "nodes": [
                    {"id": "a", "title": "打好基础", "requires": [], "done": False},
                    {"id": "b", "title": "项目交付", "requires": ["a"], "done": False},
                ],
            }
        ],
    }


def test_persistence_reconnect_conflict_and_restore(store) -> None:
    row = store.save("knowledge", {"title": "旧版", "content": "正文"})
    assert RecordStore(store.prefix).get(row["id"])["data"]["title"] == "旧版"
    updated = store.save("knowledge", {"title": "新版", "content": "新内容"}, row["id"], 1)
    with pytest.raises(VersionConflict):
        store.save("knowledge", {"title": "过期页面"}, row["id"], 1)
    removed = store.delete(row["id"], updated["version"])
    assert store.list("knowledge") == []
    restored = store.restore(row["id"], 1, removed["version"])
    assert restored["version"] == 4 and restored["data"]["title"] == "旧版"
    assert len(store.history(row["id"])) == 4


def test_two_concurrent_updates_exactly_one_succeeds(store) -> None:
    row = store.save("knowledge", {"title": "初版"})

    def update(title):
        try:
            return store.save("knowledge", {"title": title}, row["id"], 1)["version"]
        except VersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["页面 A", "页面 B"]))
    assert sorted(map(str, results)) == ["2", "conflict"]
    assert len(store.history(row["id"])) == 2


def test_snapshot_restore_is_transactional_and_preserves_history(store) -> None:
    row = store.save("knowledge", {"title": "快照前", "content": "正文"})
    snapshot = store.export()
    store.save("knowledge", {"title": "快照后", "content": "正文"}, row["id"], 1)
    added = store.save("knowledge", {"title": "后加", "content": "正文"})
    result = store.restore_snapshot(snapshot)
    assert result["restored_records"] == 2
    assert store.get(row["id"])["data"]["title"] == "快照前"
    assert store.get(added["id"], True)["deleted"]
    assert len(store.history(row["id"])) == 3


def test_snapshot_failure_rolls_back_all_prior_changes(store) -> None:
    """第二条类型冲突时，第一条已执行更新也必须回滚。"""
    for title in ("内容 A", "内容 B"):
        store.save("knowledge", {"title": title, "content": "原文"})
    snapshot = store.export()
    first, second = snapshot["records"]
    first["data"]["title"] = "不应留下的局部写入"
    second["kind"] = "plan"
    with pytest.raises(VersionConflict):
        store.restore_snapshot(snapshot)
    assert store.get(first["id"])["data"]["title"] != "不应留下的局部写入"
    assert store.get(first["id"])["version"] == 1


def test_derived_unlocking_and_done_status_are_not_persisted() -> None:
    plan = validate_plan(sample_plan())
    result = derive_plan(plan)
    assert [n["state"] for n in result["acts"][0]["nodes"]] == ["available", "locked"]
    assert "state" not in plan["acts"][0]["nodes"][0]
    plan["acts"][0]["nodes"][0]["done"] = True
    assert derive_plan(plan)["acts"][0]["nodes"][1]["state"] == "available"


@pytest.mark.parametrize("mutation", ["self", "cycle", "cross", "premature", "duplicate"])
def test_invalid_dependency_rules_are_rejected(mutation) -> None:
    plan = sample_plan()
    a, b = plan["acts"][0]["nodes"]
    if mutation == "self":
        a["requires"] = ["a"]
    elif mutation == "cycle":
        a["requires"] = ["b"]
    elif mutation == "cross":
        b["requires"] = ["external"]
    elif mutation == "premature":
        b["done"] = True
    else:
        b["id"] = "a"
    with pytest.raises(DomainError):
        validate_plan(plan)


def test_plan_stats_matches_in_memory_aggregation(store) -> None:
    """SQL 聚合口径必须与内存统计一致（M5 切换前的对照测试）。"""
    store.save("plan", validate_plan(sample_plan()))
    done_plan = sample_plan()
    done_plan["acts"][0]["nodes"][0]["done"] = True
    store.save("plan", validate_plan(done_plan))
    store.save("knowledge", {"title": "非规划记录", "content": "不计入"})
    removed = store.save("plan", validate_plan(sample_plan()))
    store.delete(removed["id"], removed["version"])

    plans = store.list("plan")
    nodes = [node for row in plans for act in row["data"]["acts"] for node in act["nodes"]]
    expected = {"node_count": len(nodes), "done_count": sum(node["done"] for node in nodes)}

    assert store.plan_stats() == expected
    assert expected == {"node_count": 4, "done_count": 1}
    assert store.count("plan") == len(plans) == 2
