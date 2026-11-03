"""OpenAPI 响应契约的纯模型测试，不依赖数据库。"""

import pytest
from pydantic import ValidationError

from rag_tech_retriever.api.models import JobsOverviewOut, QueryOut, RecordOut


def test_query_response_keeps_extra_engine_fields():
    model = QueryOut.model_validate({
        "query": "协议号",
        "engine": "全文匹配",
        "hits": [{"chunk_id": "c1"}],
        "answer": "引用内容",
        "notes": ["降级"],
        "namespace": "tech_doc",
        "trace_id": "t-1",
    })
    dumped = model.model_dump()
    assert dumped["trace_id"] == "t-1"
    assert dumped["hits"][0]["chunk_id"] == "c1"


def test_record_response_keeps_domain_derived_fields():
    model = RecordOut.model_validate({
        "id": "r1", "kind": "knowledge", "version": 2, "data": {"title": "标题"},
        "deleted": False, "updated_at": "2026-11-03T00:00:00+00:00",
    })
    dumped = model.model_dump()
    assert dumped["deleted"] is False
    assert dumped["data"]["title"] == "标题"


def test_jobs_overview_keeps_grouped_record_lists():
    model = JobsOverviewOut.model_validate({
        "as_of": "2026-11-03T00:00:00+00:00",
        "due_application_ids": ["a1"],
        "counts": {"applied": 1},
        "funnel": {"stages": []},
        "job_lead": [{"id": "j1"}],
    })
    dumped = model.model_dump()
    assert dumped["job_lead"][0]["id"] == "j1"


def test_query_response_rejects_missing_required_contract():
    with pytest.raises(ValidationError):
        QueryOut.model_validate({"query": "x"})
