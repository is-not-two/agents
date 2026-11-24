"""求职只读工具的纯逻辑测试：不依赖数据库，也不调用模型。"""

import pytest

from rag_tech_retriever.platform import agent_job_tools as tools


def lead(title="AI Agent 研发工程师", company="阿里云", jd="岗位职责：" + "x" * 400, **extra):
    return {"kind": "job_lead", "data": {"title": title, "company": company, "jd_text": jd, **extra}}


def test_summarize_lead_keeps_snippet_not_full_jd():
    summary = tools.summarize("job_lead", lead()["data"])
    assert summary["company"] == "阿里云"
    assert summary["jd_chars"] == 405
    assert len(summary["jd_snippet"]) <= tools.SNIPPET_CHARS


def test_summarize_counts_are_stable_for_each_kind():
    application = tools.summarize("application", {"title": "投递", "status": "interviewing",
                                                  "channel": "官网", "lead_id": "L1"})
    assert application["status"] == "interviewing"
    report = tools.summarize("interview_report", {"title": "一轮复盘", "round": 1,
                                                  "questions": ["a", "b"], "weak_points": ["并发"]})
    assert (report["questions"], report["weak_points"]) == (2, "并发")
    capability = tools.summarize("company_capability", {"company": "阿里云", "title": "能力",
                                                        "capabilities": [{"requirement": "must"},
                                                                         {"requirement": "nice"}]})
    assert (capability["capabilities"], capability["must"]) == (2, 1)
    resume = tools.summarize("resume_version", {"title": "简历 v2", "file_name": "cv.pdf",
                                                "parse_status": "parsed", "highlights": ["RAG"]})
    assert resume["parse_status"] == "parsed"


def test_matches_is_case_insensitive_and_filters_company():
    data = lead(company="上海人工智能实验室", jd="熟悉 RAG 与 pgvector")["data"]
    assert tools.matches("job_lead", data, "rag", "")
    assert tools.matches("job_lead", data, "", "人工智能")
    assert not tools.matches("job_lead", data, "graphql", "")
    assert not tools.matches("job_lead", data, "", "阿里云")


def test_search_filters_kinds_and_sorts_by_updated_at():
    rows = [
        {"id": "b", "kind": "job_lead", "version": 1, "updated_at": "2026-11-03T10:00:00",
         "data": lead(title="岗位 B")["data"]},
        {"id": "a", "kind": "job_lead", "version": 1, "updated_at": "2026-11-04T10:00:00",
         "data": lead(title="岗位 A")["data"]},
        {"id": "c", "kind": "application", "version": 1, "updated_at": "2026-11-05T10:00:00",
         "data": {"title": "投递 C", "status": "applied"}},
    ]
    found = tools.search(rows, kinds=["job_lead"], limit=5)
    assert [item["id"] for item in found] == ["a", "b"]
    assert all(item["kind"] == "job_lead" for item in found)
    assert [item["id"] for item in tools.search(rows, limit=2)] == ["c", "a"]


def test_search_respects_limit_bounds_and_unknown_kinds():
    rows = [{"id": str(i), "kind": "job_lead", "version": 1, "updated_at": "2026-11-03T00:00:00",
             "data": lead(title=f"岗位{i}")["data"]} for i in range(30)]
    assert len(tools.search(rows, limit=100)) == tools.MAX_LIMIT
    assert len(tools.search(rows, kinds=["not_a_kind"], limit=3)) == 3


def test_detail_clips_long_text_and_reports_truncated():
    long_jd = "x" * (tools.JD_CHARS + 10)
    row = {"id": "L1", "kind": "job_lead", "version": 2, "updated_at": "2026-11-03T00:00:00",
           "data": {"title": "岗位", "company": "公司", "jd_text": long_jd, "notes": "n" * 900}}
    value = tools.detail(row)
    assert value["truncated"] == ["jd_text", "notes"]
    assert len(value["data"]["jd_text"]) == tools.JD_CHARS
    assert value["version"] == 2


def test_detail_rejects_non_job_records():
    with pytest.raises(ValueError):
        tools.detail({"id": "x", "kind": "knowledge", "data": {}})
