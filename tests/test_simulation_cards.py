"""Pin the simulation-to-learning boundary without a live database or model."""
from contextlib import contextmanager

import pytest

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.learning import LearningService
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict

CONFIRM = "确认创建复习卡"


class Store:
    prefix = records = "fixture"
    config = ConfigLoader.load_default()

    def __init__(self):
        self.rows = {"run": {"id": "run", "kind": "agent_session", "version": 2, "deleted": False, "data": {
            "kind": "graph", "private_interview": True, "status": "completed", "input": {"resume_id": "private-resume"},
            "node_outputs": {"boss_review": {"evidence": {
                "facts": ["原简历私有原句"], "pending": ["说明取样范围"], "suggestions": ["练习说明回滚条件"],
            }}},
        }}}

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, sql, params):
        self.row = self.rows.get(params[0])

    def fetchone(self):
        return self.row

    def _save(self, cur, kind, data, record_id, version):
        assert cur is self and version is None and record_id not in self.rows
        row = {"id": record_id, "kind": kind, "version": 1, "data": data, "deleted": False}
        self.rows[record_id] = row
        return row

    def _serialize(self, row):
        return row


def test_confirmed_simulation_cards_copy_only_selected_exercise_and_reuse():
    store = Store()
    service = LearningService(store)
    points = ["练习说明回滚条件"]
    with pytest.raises(DomainError):
        service.from_simulation("run", 2, points, "")
    assert len(store.rows) == 1
    created = service.from_simulation("run", 2, points, CONFIRM)["created"]
    assert len(created) == 1
    assert created[0]["data"]["title"] == points[0]
    assert created[0]["data"]["source"] == "manual" and not created[0]["data"]["source_id"]
    assert "原简历私有原句" not in str(created) and "private-resume" not in str(created)
    assert service.from_simulation("run", 2, points, CONFIRM) == {"created": [], "reused": created}


def test_simulation_cards_reject_private_fact_wrong_version_and_unfinished_result():
    store = Store()
    service = LearningService(store)
    with pytest.raises(DomainError):
        service.from_simulation("run", 2, ["原简历私有原句"], CONFIRM)
    with pytest.raises(VersionConflict):
        service.from_simulation("run", 1, ["说明取样范围"], CONFIRM)
    with pytest.raises(RecordMissing):
        service.from_simulation("missing", 2, ["说明取样范围"], CONFIRM)
    store.rows["run"]["data"]["status"] = "failed"
    with pytest.raises(DomainError):
        service.from_simulation("run", 2, ["说明取样范围"], CONFIRM)
    assert len(store.rows) == 1
