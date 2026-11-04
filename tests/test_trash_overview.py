"""回收站汇总的边界：只收公开工作区类型，摘要不夹带大字段。"""

from __future__ import annotations

from rag_tech_retriever.api.routes.history import (
    TRASH_KINDS,
    _trash_subtitle,
    _trash_title,
)


def test_trash_kinds_exclude_private_and_audit_records():
    """私密愿望/日记与运行审计不能出现在侧栏回收站。"""
    forbidden = {
        "wish", "diary", "workflow_run", "learning_review",
        "notification_outbox", "agent_memory", "agent_session",
    }
    assert forbidden.isdisjoint(TRASH_KINDS)
    assert {"knowledge", "bookmark", "plan", "lesson", "learning_card"} <= set(TRASH_KINDS)


def test_job_title_combines_company_and_role():
    assert _trash_title("job_lead", {"company": "示例公司", "title": "后端工程师"}) == (
        "示例公司 / 后端工程师"
    )
    assert _trash_title("application", {"company": "示例公司", "role": "后端工程师"}) == (
        "示例公司 / 后端工程师"
    )


def test_title_falls_back_to_payload_then_kind_label():
    assert _trash_title("knowledge", {"title": "排查记录"}) == "排查记录"
    assert _trash_title("learning_card", {"question": "为什么连接池会借满？"}) == (
        "为什么连接池会借满？"
    )
    assert _trash_title("resume_version", {}) == "简历版本"


def test_subtitle_is_bounded():
    long_text = "x" * 500
    assert len(_trash_subtitle("knowledge", {"content": long_text})) == 80
    assert len(_trash_subtitle("bookmark", {"url": "https://" + long_text})) == 120
    assert _trash_subtitle("plan", {"title": "规划"}) == ""
