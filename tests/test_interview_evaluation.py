"""规则评分：确定性、量化差异、失败关闭与数据隔离。"""
import pytest

from rag_tech_retriever.domains.interview_evaluation import extract_terms, score_answers
from rag_tech_retriever.domains.interview_prep import validate_interview_prep
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.interview_prep_service import (
    InterviewPrepService,
    load_interview_config,
)
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict

JD = "需要 Python 与 FastAPI 经验，要求复盘能力"


def _rubric():
    return load_interview_config()["rubric"]


def _turns(answer):
    return [{"q": "介绍一个项目", "answer": answer, "suggestion": ""}]


class _Store:
    def __init__(self, answer="首先用 Python 写 FastAPI 服务，结果 QPS 提升 3 倍，最后复盘验证了指标。"):
        self.rows = {
            "prep1": {"id": "prep1", "kind": "interview_prep", "version": 1,
                      "data": {"title": "模拟面试", "lead_id": "l1", "resume_id": "r1",
                               "turns": _turns(answer), "notes": ""}},
        }

    def get(self, record_id):
        if record_id == "l1":
            return {"kind": "job_lead", "data": {"jd_text": JD}}
        if record_id == "r1":
            return {"kind": "resume_version", "data": {}}
        if record_id in self.rows:
            return self.rows[record_id]
        raise RecordMissing("记录不存在")

    def save(self, kind, data, record_id=None, version=None):
        if record_id in self.rows and version != self.rows[record_id]["version"]:
            raise VersionConflict("记录已更新")
        row = {"id": record_id, "kind": kind, "version": (version or 0) + 1, "data": data}
        self.rows[record_id] = row
        return row


class _Resumes:
    def document(self, record_id):
        return {"text": "简历正文"}


def _service(store=None, config=None):
    return InterviewPrepService(store or _Store(), _Resumes(),
                                config=config if config is not None else load_interview_config())


def test_extract_terms_is_sorted_and_deduplicated() -> None:
    assert extract_terms("Python FastAPI Python") == ["FastAPI", "Python"]
    assert extract_terms(JD) == extract_terms(JD)


def test_same_input_produces_identical_result() -> None:
    turns = _turns("首先用 Python 写 FastAPI 服务，结果 QPS 提升 3 倍。")
    assert score_answers(turns, JD, _rubric()) == score_answers(turns, JD, _rubric())


def test_empty_turns_are_rejected() -> None:
    with pytest.raises(DomainError):
        score_answers([], JD, _rubric())


def test_richer_answer_scores_higher_with_dimension_evidence() -> None:
    rubric = _rubric()
    weak = score_answers(_turns("做过"), JD, rubric)
    strong = score_answers(_turns(
        "首先用 Python 写 FastAPI 服务，结果 QPS 提升 3 倍，最后复盘验证了指标。"), JD, rubric)
    assert strong["score"] > weak["score"]
    assert set(strong["dimensions"]) == {"具体性", "证据", "结构", "岗位关联"}
    assert strong["dimensions"]["岗位关联"] > weak["dimensions"]["岗位关联"]
    assert strong["source"] == "rules" and "规则评分" in strong["notes"]
    assert isinstance(strong["weak_points"], list)


def test_validator_keeps_evaluation_and_rejects_bad_shape() -> None:
    result = score_answers(_turns("做过"), JD, _rubric())
    row = validate_interview_prep({"title": "模拟面试", "turns": _turns("做过"),
                                   "evaluation": result})
    assert row["evaluation"] == result
    with pytest.raises(DomainError):
        validate_interview_prep({"title": "x", "turns": _turns("做过"),
                                 "evaluation": [1]})


def test_evaluate_rejects_model_source_and_unanswered_session() -> None:
    with pytest.raises(DomainError):
        _service().evaluate("prep1", 1, source="model")
    blank = _Store(answer="")
    with pytest.raises(DomainError):
        _service(blank).evaluate("prep1", 1)


def test_evaluate_saves_rules_result_under_dedicated_kind() -> None:
    store = _Store()
    row = _service(store).evaluate("prep1", 1)
    assert row["kind"] == "interview_prep" and row["version"] == 2
    assert row["data"]["evaluation"]["source"] == "rules"
    assert row["data"]["evaluation"]["score"] > 0
    assert all(r["kind"] != "interview_report" for r in store.rows.values())
