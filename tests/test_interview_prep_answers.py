"""模拟面试作答契约：服务端显式合并、版本冲突与边界拒绝。"""
from copy import deepcopy

import pytest

from rag_tech_retriever.domains.interview_prep import validate_answers
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.interview_prep_service import InterviewPrepService
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict


def _prep_data():
    return {
        "title": "模拟面试", "company": "甲公司", "role": "AI 产品经理",
        "lead_id": "l1", "resume_id": "r1", "mode": "practice",
        "turns": [{"q": "问题一", "answer": "", "suggestion": ""},
                  {"q": "问题二", "answer": "", "suggestion": ""}],
        "notes": "", "audio": {},
    }


class _PrepStore:
    def __init__(self, data=None):
        self.rows = {
            "prep1": {"id": "prep1", "kind": "interview_prep",
                      "version": 1, "data": data or _prep_data()}
        }
        self.saved = []

    def get(self, record_id):
        if record_id == "l1":
            return {"kind": "job_lead", "data": {"jd_text": "需要 Python"}}
        if record_id == "r1":
            return {"kind": "resume_version", "data": {}}
        if record_id in self.rows:
            return deepcopy(self.rows[record_id])
        raise RecordMissing("记录不存在")

    def save(self, kind, data, record_id=None, version=None):
        if record_id in self.rows and version != self.rows[record_id]["version"]:
            raise VersionConflict("记录已更新")
        row = {"id": record_id, "kind": kind,
               "version": (version or 0) + 1, "data": deepcopy(data)}
        self.rows[record_id] = row
        self.saved.append(row)
        return row


class _Resumes:
    def document(self, record_id):
        return {"text": "简历正文"}


def _service(store=None):
    return InterviewPrepService(store or _PrepStore(), _Resumes(), config={})


def test_validate_answers_normalizes_and_sorts() -> None:
    turns = [{"q": "a"}, {"q": "b"}, {"q": "c"}]
    result = validate_answers(
        turns, [{"index": 2, "answer": "三"}, {"index": 0, "answer": "一"}])
    assert [row["index"] for row in result] == [0, 2]


def test_validate_answers_rejects_bad_index_duplicate_and_empty() -> None:
    turns = [{"q": "a"}]
    with pytest.raises(DomainError):
        validate_answers(turns, [])
    with pytest.raises(DomainError):
        validate_answers(turns, [{"index": 5, "answer": "x"}])
    with pytest.raises(DomainError):
        validate_answers(turns, [{"index": 0}, {"index": 0}])
    with pytest.raises(DomainError):
        validate_answers(turns, [{"index": True, "answer": "x"}])


def test_submit_answers_merges_only_named_turns_and_bumps_version() -> None:
    store = _PrepStore()
    row = _service(store).submit_answers("prep1", 1, [{"index": 1, "answer": "我的回答"}])
    assert row["version"] == 2
    assert row["data"]["turns"][0]["answer"] == ""
    assert row["data"]["turns"][1]["answer"] == "我的回答"
    assert store.rows["prep1"]["data"]["turns"][1]["answer"] == "我的回答"


def test_submit_answers_rejects_wrong_kind_stale_version_and_bad_index() -> None:
    store = _PrepStore()
    store.rows["other"] = {"id": "other", "kind": "interview_report",
                           "version": 1, "data": {"turns": []}}
    with pytest.raises(DomainError):
        _service(store).submit_answers("other", 1, [{"index": 0, "answer": "x"}])
    with pytest.raises(VersionConflict):
        _service(store).submit_answers("prep1", 99, [{"index": 0, "answer": "x"}])
    with pytest.raises(DomainError):
        _service(store).submit_answers("prep1", 1, [{"index": 9, "answer": "x"}])
