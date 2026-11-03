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
    """简历版本：公开记录只留元数据，正文与结构化段落存本机私密文件。"""
    digest = text(payload.get("file_hash", ""), "文件 SHA256", 64)
    if digest and not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise DomainError("文件 SHA256 必须为 64 位十六进制")
    document_id = text(payload.get("document_id", ""), "简历文档 ID", 64)
    if document_id and not re.fullmatch(r"[a-f0-9]{64}", document_id):
        raise DomainError("简历文档 ID 必须为 64 位十六进制")
    size = payload.get("size", 0)
    if type(size) is not int or not 0 <= size <= 20_000_000:
        raise DomainError("简历文件大小必须为 0–20MB 的整数")
    status = payload.get("parse_status", "")
    if status not in {"", "pending", "parsed", "failed"}:
        raise DomainError("简历解析状态不支持")
    return {"title": text(payload.get("title", ""), "简历版本名称", 160, True),
            "file_hash": digest.lower(), "highlights": strings(payload.get("highlights", []), "简历亮点"),
            "document_id": document_id,
            "file_name": text(payload.get("file_name", ""), "简历文件名", 200),
            "mime": text(payload.get("mime", ""), "简历类型", 80),
            "size": size, "parse_status": status}


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


CAPABILITY_REQUIREMENTS = ("must", "nice")
CAPABILITY_STATUSES = ("evidence", "pending", "missing")


def validate_capability(payload: dict) -> dict:
    """目标公司能力清单：只记录用户提供或 JD 摘录，不自动判定个人是否具备。"""
    company = text(payload.get("company", ""), "公司", 160, True)
    role = text(payload.get("role", ""), "岗位", 160)
    items = payload.get("capabilities", [])
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise DomainError("请记录 1–30 条目标能力")
    clean: list[dict] = []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise DomainError("能力条目格式错误")
        name = text(item.get("name", ""), "能力名称", 120, True)
        key = name.casefold()
        if key in names:
            raise DomainError("能力名称重复：" + name)
        names.append(key)
        requirement = item.get("requirement", "must")
        if requirement not in CAPABILITY_REQUIREMENTS:
            raise DomainError("能力要求只能是 must 或 nice")
        level = item.get("level", 3)
        if type(level) is not int or not 1 <= level <= 5:
            raise DomainError("能力重要度必须为 1–5 的整数")
        status = item.get("status", "pending")
        if status not in CAPABILITY_STATUSES:
            raise DomainError("证据状态不支持")
        clean.append(
            {
                "name": name,
                "requirement": requirement,
                "level": level,
                "status": status,
                "evidence": text(item.get("evidence", ""), "能力证据", 1000),
            }
        )
    return {
        "title": company + (" / " + role if role else ""),
        "company": company,
        "role": role,
        "source": text(payload.get("source", ""), "来源", 2000),
        "capabilities": clean,
        "notes": text(payload.get("notes", ""), "能力备注", 10000),
    }


def funnel_stages(
    leads: list[dict], applications: list[dict], reports: list[dict], *,
    now: str, week_start: str, week_end: str, target: int,
) -> dict:
    """漏斗只统计当前有效记录；进面按已登记复盘计，offer 按当前状态计。

    进面集合不强制包含在 offer 集合内：业务状态可以在未写复盘时直接推进，
    因此各阶段只保证口径可复算，不保证严格嵌套；前端需注明这一点。
    """
    applied = [row for row in applications if row["data"].get("applied_at")]
    interviewed_ids = {row["data"].get("application_id") for row in reports}
    interviewed = [row for row in applied if row["id"] in interviewed_ids]
    offered = [row for row in applications if row["data"]["status"] == "offered"]
    weekly = sum(
        week_start <= row["data"]["applied_at"] < week_end for row in applied
    )

    def rate(part: int, whole: int) -> float | None:
        """空分母返回 null，页面显示“暂不计算”，不伪装成 0%。"""
        return round(part / whole, 4) if whole else None

    return {
        "stages": {
            "collected": len(leads),
            "applied": len(applied),
            "interviewed": len(interviewed),
            "offered": len(offered),
        },
        "rates": {
            "applied_per_collected": rate(len(applied), len(leads)),
            "interviewed_per_applied": rate(len(interviewed), len(applied)),
            "offered_per_interviewed": rate(len(offered), len(interviewed)),
        },
        "weekly": {
            "applications": weekly,
            "target": target,
            "week_start": week_start,
            "week_end": week_end,
            "met": weekly >= target,
        },
        "as_of": now,
    }


VALIDATORS = {"job_lead": validate_lead, "application": validate_application,
              "interview_report": validate_report, "resume_version": validate_resume,
              "company_capability": validate_capability}


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
