"""AI 简历优化：模板缺失/未配置模型失败关闭，人工确认后另存而非覆盖简历。"""
import pytest

from rag_tech_retriever.common.provider import ProviderError
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.resume_optimizer import CONFIRMATION, ResumeOptimizer


class _Store:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def save(self, kind: str, data: dict, *args) -> dict:
        row = {"id": f"{kind}-{len(self.rows)}", "kind": kind, "version": 1, "data": data}
        self.rows.append(row)
        return row


def test_templates_never_expose_system_prompt() -> None:
    items = ResumeOptimizer(None, None).templates()
    assert all(set(item) == {"id", "name"} for item in items)


def test_missing_template_fails_closed() -> None:
    with pytest.raises(DomainError):
        ResumeOptimizer(_Store(), None).draft("no-such-template", "resume-1", "lead-1")


def test_apply_requires_explicit_confirmation() -> None:
    with pytest.raises(DomainError):
        ResumeOptimizer(_Store(), None).apply("标题", "草稿", "")


def test_apply_saves_knowledge_not_resume_version() -> None:
    store = _Store()
    row = ResumeOptimizer(store, None).apply("优化记录", "改写草稿", CONFIRMATION)
    assert row["kind"] == "knowledge"
    assert row["data"]["content"] == "改写草稿"
    assert all(r["kind"] != "resume_version" for r in store.rows)


class _Conn:
    def load(self) -> dict:
        return {"api_key": "test-key", "base_url": "https://example.invalid",
                "model": "test-model", "revision": "test"}


class _Resumes:
    def document(self, record_id: str) -> dict:
        return {"text": "简历正文：Python 项目"}


class _LeadStore(_Store):
    def get(self, record_id: str) -> dict:
        return {"kind": "job_lead", "data": {"jd_text": "需要 Python"}}


def _transport(config, body, timeout, max_chars):
    _transport.seen = body
    return {"choices": [{"message": {"content": "改写草稿"}}]}


def test_templates_ship_three_editable_presets() -> None:
    items = ResumeOptimizer(None, None).templates()
    assert {item["id"] for item in items} == {"product-manager", "fullstack", "general"}


def test_system_prompt_stays_server_side() -> None:
    template = ResumeOptimizer(None, None)._template("general")
    assert "禁止添加" in template["system"]
    assert all("system" not in item for item in ResumeOptimizer(None, None).templates())


def test_draft_with_injected_transport_uses_jd_and_resume() -> None:
    result = ResumeOptimizer(_LeadStore(), _Resumes(), _Conn()).draft(
        "general", "r1", "l1", post=_transport
    )
    assert result["draft"] == "改写草稿"
    assert result["quality_verified"] is False
    content = _transport.seen["messages"][1]["content"]
    assert "需要 Python" in content and "Python 项目" in content


def test_draft_fails_closed_without_model_connection() -> None:
    with pytest.raises(ProviderError):
        ResumeOptimizer(_LeadStore(), _Resumes(), None).draft("general", "r1", "l1")
