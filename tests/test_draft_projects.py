"""Deterministic model boundary and racing requests against versioned draft rows."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.draft_projects import DraftProjects, planned
from rag_tech_retriever.platform.record_store import VersionConflict

PLAN = {"stages": [
    {"id": "orders", "title": "订单页", "task": "订单列表"},
    {"id": "roles", "title": "角色权限", "task": "权限", "depends": ["orders"]},
    {"id": "fields", "title": "订单字段", "task": "字段"},
]}


def preview(summary):
    return {"summary": summary, "columns": ["订单号"], "rows": [["样例一"]], "roles": ["财务", "仓库"],
            "initial": "待审", "actions": [{"label": "批准", "roles": ["财务"], "before": "待审", "after": "已批准"}]}


class Store:
    def __init__(self):
        self.row = None
        self.lock = Lock()

    def save(self, kind, data, record_id=None, version=None):
        with self.lock:
            if record_id and version != self.row["version"]:
                raise VersionConflict("stale")
            self.row = {"id": "project", "kind": kind, "version": (version or 0) + 1, "data": deepcopy(data)}
            return deepcopy(self.row)

    def get(self, _record_id):
        with self.lock:
            return deepcopy(self.row)


def test_review_only_blocks_dependencies_and_rollback_keeps_unaffected_work():
    calls = []

    def model(prompt, data):
        if "具体、可选" in prompt:
            return {"options": ["仓库打开待发货", "按角色选择首页"]}
        if "stage" not in data:
            return PLAN
        if data["feedback"]:
            assert data["prior_draft"]["summary"] == "orders"
        calls.append((data["stage"]["id"], data["feedback"]))
        return preview(data["stage"]["id"] + data["feedback"])

    service = DraftProjects(Store(), None, model)
    row = service.create("订单后台")

    def do(action, node="", value=""):
        nonlocal row
        if action == "advance":
            row = service.advance(row["id"], row["version"])
        else:
            row = service.change(row["id"], row["version"], action, node, value)
        return row["data"]

    do("advance")
    do("gate", "orders", "仓库可以看到订单")
    do("advance")
    assert do("advance")["status"] == "awaiting_review"
    assert [key for key, _ in calls] == ["orders", "fields"]
    do("approve", "orders")
    assert do("advance")["status"] == "completed"
    assert service.choices(row["id"], row["version"], "orders", "入口不对")[0] == "仓库打开待发货"
    old = row
    data = do("revise", "orders", "默认打开待发货")
    assert data["status"] == "paused" and {item["id"] for item in data["history"]} == {"orders", "roles"}
    assert data["stages"][2]["draft"] == old["data"]["stages"][2]["draft"]
    with pytest.raises(VersionConflict):
        service.change(old["id"], old["version"], "approve", "orders", "")
    do("resume")
    assert do("advance")["status"] == "awaiting_review"
    assert calls[-1] == ("orders", "默认打开待发货")
    do("approve", "orders")
    assert do("advance")["status"] == "completed"
    assert [key for key, _ in calls].count("fields") == 1
    before = row["data"]["stages"][1]["draft"]
    assert do("gate", "orders", "补看列表，但不改草稿")["status"] == "awaiting_review"
    assert do("approve", "orders")["stages"][1]["draft"] == before


def test_pause_fences_late_result_and_rejects_duplicate_advance():
    entered, release = Event(), Event()

    def model(*_):
        entered.set()
        assert release.wait(5)
        return PLAN

    service = DraftProjects(Store(), None, model)
    row = service.create("后台")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(service.advance, row["id"], row["version"])
        try:
            assert entered.wait(5)
            current = service.get(row["id"])
            with pytest.raises(VersionConflict):
                service.advance(row["id"], row["version"])
            paused = service.change(current["id"], current["version"], "pause", "", "")
        finally:
            release.set()
        assert running.result(5) == paused
    assert paused["data"]["status"] == "paused" and not paused["data"]["stages"]


def test_invalid_plan_cannot_insert_dependencies_or_leave_project_running():
    broken = deepcopy(PLAN)
    broken["stages"][0]["depends"] = ["roles"]
    with pytest.raises(DomainError):
        planned(broken)
    service = DraftProjects(Store(), None, lambda *_: broken)
    row = service.create("后台")
    failed = service.advance(row["id"], row["version"])
    assert failed["data"]["status"] == "failed" and not failed["data"]["active"]
    assert service.change(failed["id"], failed["version"], "resume", "", "")["data"]["status"] == "ready"
