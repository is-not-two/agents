"""求职数据规则：证据与状态独立于模型、数据库和页面。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from rag_tech_retriever.domains.life_planning import DomainError, text

STATUSES = ("collected", "applied", "following", "interviewing", "offered", "rejected")
TRANSITIONS = {
    "collected": {"applied", "rejected"},
    "applied": {"following", "interviewing", "rejected"},
    "following": {"interviewing", "rejected"},
    "interviewing": {"offered", "rejected"},
    "offered": set(), "rejected": set(),
}


def timestamp(value: object, label: str) -> str:
    """空值表示未设置，非空时间必须带时区，统一存 UTC。"""
    value = text(value, label, 80)
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise DomainError(f"{label}必须是带时区的有效日期时间") from exc


def strings(value: object, label: str, maximum: int = 30) -> list[str]:
    """有界文本列表，不把任意对象隐式转成文本。"""
    if not isinstance(value, list) or len(value) > maximum:
        raise DomainError(f"{label}最多 {maximum} 条")
    return list(dict.fromkeys(text(item, label, 1000, True) for item in value))


def validate_lead(payload: dict) -> dict:
    """岗位原文留档；URL 仅作来源链接，不由服务端抓取。"""
    source = text(payload.get("source_url", ""), "来源链接", 2000)
    if source:
        try:
            url = urlsplit(source)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError
        except ValueError as exc:
            raise DomainError("来源链接仅支持不含账号密码的 HTTP/HTTPS 地址") from exc
    return {"title": text(payload.get("title", ""), "岗位名称", 160, True),
            "company": text(payload.get("company", ""), "公司", 160, True),
            "source_url": source, "jd_text": text(payload.get("jd_text", ""), "岗位原文", 50000),
            "notes": text(payload.get("notes", ""), "岗位备注", 10000)}


def validate_resume(payload: dict) -> dict:
    """只留简历版本元数据，不读取或移动用户简历文件。"""
    digest = text(payload.get("file_hash", ""), "文件 SHA256", 64)
    if digest and not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise DomainError("文件 SHA256 必须为 64 位十六进制")
    return {"title": text(payload.get("title", ""), "简历版本名称", 160, True),
            "file_hash": digest.lower(), "highlights": strings(payload.get("highlights", []), "简历亮点")}


def validate_application(payload: dict) -> dict:
    """状态迁移由服务层对照当前版本校验，快照只校验持久字段。"""
    status = payload.get("status", "collected")
    if not isinstance(status, str) or status not in STATUSES:
        raise DomainError("投递状态不支持")
    return {"title": text(payload.get("title", ""), "投递名称", 400),
            "lead_id": text(payload.get("lead_id", ""), "岗位 ID", 100, True),
            "resume_version_id": text(payload.get("resume_version_id", ""), "简历版本 ID", 100),
            "channel": text(payload.get("channel", ""), "投递渠道", 80), "status": status,
            "applied_at": timestamp(payload.get("applied_at", ""), "投递时间"),
            "follow_up_at": timestamp(payload.get("follow_up_at", ""), "下次跟进时间"),
            "notes": text(payload.get("notes", ""), "投递备注", 20000)}


def validate_report(payload: dict) -> dict:
    """真实面试问题、自评与行动；薄弱点只作为待确认候选。"""
    round_number = payload.get("round", 1)
    if type(round_number) is not int or not 1 <= round_number <= 20:
        raise DomainError("面试轮次必须为 1–20 的整数")
    questions = payload.get("questions", [])
    if not isinstance(questions, list) or not 1 <= len(questions) <= 50:
        raise DomainError("请记录 1–50 个实际面试问题")
    clean = []
    for question in questions:
        if not isinstance(question, dict) or type(question.get("rating", 0)) is not int or not 0 <= question.get("rating", 0) <= 3:
            raise DomainError("问题自评必须为 0–3 的整数")
        clean.append({"q": text(question.get("q", ""), "面试问题", 2000, True),
                      "answer_summary": text(question.get("answer_summary", ""), "回答复盘", 4000),
                      "rating": question.get("rating", 0)})
    return {"title": text(payload.get("title", ""), "复盘名称", 450),
            "application_id": text(payload.get("application_id", ""), "投递 ID", 100, True),
            "round": round_number, "interviewed_at": timestamp(payload.get("interviewed_at", ""), "面试时间"),
            "questions": clean, "weak_points": strings(payload.get("weak_points", []), "薄弱点"),
            "next_actions": strings(payload.get("next_actions", []), "下一步行动"),
            "notes": text(payload.get("notes", ""), "复盘备注", 10000)}


VALIDATORS = {"job_lead": validate_lead, "application": validate_application,
              "interview_report": validate_report, "resume_version": validate_resume}


def validate_references(records: list[dict]) -> None:
    """当前快照的有效业务记录不能引用缺失、错误类型或已删除的父记录。"""
    indexed = {row["id"]: row for row in records}
    for row in records:
        if row.get("deleted") or row["kind"] not in VALIDATORS:
            continue
        pairs = {"application": [("lead_id", "job_lead"), ("resume_version_id", "resume_version")],
                 "interview_report": [("application_id", "application")]}.get(row["kind"], [])
        for field, kind in pairs:
            reference = row["data"].get(field, "")
            if not reference and field == "resume_version_id":
                continue
            parent = indexed.get(reference)
            if parent is None or parent["kind"] != kind or parent.get("deleted", False):
                raise DomainError("求职备份含缺失、已删除或错误类型的关联记录")
