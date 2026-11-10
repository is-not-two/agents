"""模拟面试：契约边界、配置抽离、关联校验与真实复盘隔离。"""
import json

import pytest

from rag_tech_retriever.common.provider import ProviderError
from rag_tech_retriever.domains.interview_prep import validate_interview_prep
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.interview_prep_service import (
    InterviewPrepService,
    load_interview_config,
)
from rag_tech_retriever.platform.record_store import RecordMissing

LEAD = {"kind": "job_lead", "data": {
    "title": "AI 产品经理", "company": "甲公司", "jd_text": "需要沟通能力与 Python"}}
RESUME = {"kind": "resume_version", "data": {}}


class _Store:
    def __init__(self, lead=None, resume=None):
        self.lead = lead or LEAD
        self.resume = RESUME if resume is None else resume
        self.rows = []

    def get(self, record_id):
        if record_id == "l1":
            return dict(self.lead)
        if record_id == "r1":
            return dict(self.resume)
        raise RecordMissing("记录不存在")

    def save(self, kind, data, *args):
        row = {"id": f"{kind}-{len(self.rows)}", "kind": kind, "version": 1, "data": data}
        self.rows.append(row)
        return row


class _Resumes:
    def __init__(self, text="简历正文：负责过 Python 项目"):
        self.text = text

    def document(self, record_id):
        return {"text": self.text}


class _Conn:
    def load(self):
        return {"api_key": "k", "base_url": "https://example.invalid",
                "model": "m", "revision": "test"}


def _post(payload):
    def post(config, body, timeout, max_chars):
        _post.seen = body
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return {"choices": [{"message": {"content": content}}]}
    return post


def _service(store=None, resumes=None, connection=None, config=None):
    return InterviewPrepService(store or _Store(), resumes or _Resumes(),
                                connection, config)


def test_validator_defaults_and_audio_bound() -> None:
    row = validate_interview_prep({"title": "模拟面试", "turns": [{"q": "问题"}]})
    assert row["mode"] == "practice" and row["audio"] == {}
    assert row["turns"][0]["answer"] == ""
    with pytest.raises(DomainError):
        validate_interview_prep({"title": "x", "turns": [{"q": "q"}], "audio": [1]})


def test_validator_rejects_bad_mode_and_empty_turns() -> None:
    with pytest.raises(DomainError):
        validate_interview_prep({"title": "x", "turns": [{"q": "q"}], "mode": "magic"})
    with pytest.raises(DomainError):
        validate_interview_prep({"title": "x", "turns": []})


def test_rules_mode_generates_five_questions_without_answers() -> None:
    draft = _service().generate("l1", "r1", "practice")
    assert len(draft["turns"]) == 5
    assert all(t["q"] and not t["answer"] and not t["suggestion"] for t in draft["turns"])
    assert "规则模板题" in draft["notes"]


def test_rule_questions_and_prompt_come_from_config() -> None:
    config = load_interview_config()
    assert "你是面试官" in config["system_prompt"]
    draft = _service(config=config).generate("l1", "r1")
    assert len(draft["turns"]) == len(config["rule_questions"])
    payload = {"turns": [{"q": "问题", "answer": "示范回答", "suggestion": "补证据"}]}
    _service(connection=_Conn()).generate(
        "l1", "r1", "full", use_model=True, post=_post(payload)
    )
    body = _post.seen
    assert config["system_prompt"] in body["messages"][0]["content"]
    assert body["max_tokens"] == config["generation"]["max_tokens"]


def test_custom_config_changes_questions_without_code_change() -> None:
    config = {**load_interview_config(), "rule_questions": ["只问一个：{company}"]}
    draft = _service(config=config).generate("l1", "r1")
    assert len(draft["turns"]) == 1 and "甲公司" in draft["turns"][0]["q"]


def test_generate_requires_jd_and_resume_text() -> None:
    with pytest.raises(DomainError):
        _service(store=_Store(lead={"kind": "job_lead", "data": {"jd_text": ""}})).generate(
            "l1", "r1")
    with pytest.raises(DomainError):
        _service(resumes=_Resumes("")).generate("l1", "r1")


def test_voice_mode_is_reserved_not_generated() -> None:
    with pytest.raises(DomainError):
        _service().generate("l1", "r1", "voice")


def test_model_mode_fails_closed_without_connection() -> None:
    with pytest.raises(ProviderError):
        _service().generate("l1", "r1", "full", use_model=True)


def test_model_full_mode_uses_jd_and_resume_and_validates_output() -> None:
    payload = {"turns": [{"q": "问题", "answer": "示范回答", "suggestion": "补证据"}]}
    draft = _service(connection=_Conn()).generate(
        "l1", "r1", "full", use_model=True, post=_post(payload))
    assert draft["turns"][0]["answer"] == "示范回答"
    content = _post.seen["messages"][1]["content"]
    assert "需要沟通能力与 Python" in content and "Python 项目" in content


def test_model_invalid_json_is_rejected() -> None:
    with pytest.raises(DomainError):
        _service(connection=_Conn()).generate(
            "l1", "r1", "full", use_model=True, post=_post("not json"))


def test_save_uses_dedicated_kind_not_interview_report() -> None:
    store = _Store()
    service = _service(store=store)
    row = service.save(service.generate("l1", "r1"))
    assert row["kind"] == "interview_prep"
    assert all(r["kind"] != "interview_report" for r in store.rows)


def test_save_rejects_orphan_or_wrong_type_references() -> None:
    service = _service()
    draft = service.generate("l1", "r1")
    with pytest.raises(DomainError):
        service.save({**draft, "lead_id": "missing"})
    with pytest.raises(DomainError):
        service.save({**draft, "resume_id": "l1"})
    with pytest.raises(DomainError):
        service.save({**draft, "lead_id": ""})
