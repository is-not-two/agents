"""复习卡和不可变复习记录规则；模型不决定调度或写入权限。"""
from __future__ import annotations

from datetime import datetime, timedelta

from rag_tech_retriever.domains.jobs import timestamp
from rag_tech_retriever.domains.life_planning import DomainError, text


def validate_card(payload: dict) -> dict:
    """正文、来源与调度完整可导出；服务层禁止客户端伪造来源和进度。"""
    source = payload.get("source", "manual")
    if not isinstance(source, str) or source not in {"manual", "interview", "jd_gap"}:
        raise DomainError("复习卡来源不支持")
    paused = payload.get("paused", False)
    if type(paused) is not bool:
        raise DomainError("暂停开关必须为布尔值")
    interval = payload.get("interval_days", 0)
    repetitions = payload.get("repetitions", 0)
    ease = payload.get("ease", 2.5)
    if type(interval) is not int or not 0 <= interval <= 365 or type(repetitions) is not int or not 0 <= repetitions <= 100000:
        raise DomainError("复习间隔或次数不合法")
    if type(ease) not in {float, int} or not 1.3 <= ease <= 3.0:
        raise DomainError("复习难度系数不合法")
    source_id = text(payload.get("source_id", ""), "来源记录 ID", 100)
    source_version = payload.get("source_version", 0)
    if type(source_version) is not int or source_version < 0 or source_version > 2147483647:
        raise DomainError("来源版本不合法")
    if source != "manual" and (not source_id or source_version < 1):
        raise DomainError("复习来源缺少记录及版本")
    if source == "manual" and (source_id or source_version):
        raise DomainError("手工卡片不能伪造来源引用")
    due = timestamp(payload.get("due_at", ""), "复习时间")
    if not due:
        raise DomainError("请设置复习时间")
    return {"title": text(payload.get("title", ""), "复习问题", 1000, True),
            "answer_ref": text(payload.get("answer_ref", ""), "答案或资料引用", 10000),
            "source": source, "source_id": source_id, "source_version": source_version,
            "source_key": text(payload.get("source_key", ""), "来源条目标识", 64),
            "due_at": due, "paused": paused, "interval_days": interval,
            "ease": float(ease), "repetitions": repetitions,
            "last_reviewed_at": timestamp(payload.get("last_reviewed_at", ""), "上次复习时间")}


def next_schedule(card: dict, rating: int, reviewed_at: str, policy: dict) -> dict:
    """简化四档调度；所有变动与上下限来自配置，不处罚漏答天数。"""
    if type(rating) is not int or not 0 <= rating <= 3:
        raise DomainError("复习自评必须为 0–3：忘了/困难/记得/熟练")
    at = datetime.fromisoformat(timestamp(reviewed_at, "复习时间"))
    previous = card["repetitions"]
    ease = min(policy["max_ease"], max(policy["min_ease"], card["ease"] + policy["ease_changes"][rating]))
    if rating == 0 or previous == 0:
        days = policy["first_days"][rating]
    elif previous == 1:
        days = policy["second_days"][rating]
    else:
        multiplier = policy["difficult_multiplier"] if rating == 1 else ease
        days = max(1, round(card["interval_days"] * multiplier))
    days = min(policy["max_interval_days"], days)
    return {**card, "due_at": (at + timedelta(days=days)).isoformat(), "interval_days": days,
            "ease": ease, "repetitions": 0 if rating == 0 else previous + 1,
            "last_reviewed_at": at.isoformat()}


def validate_review(payload: dict) -> dict:
    """复习证据不可通过普通编辑篡改。"""
    rating = payload.get("rating")
    version = payload.get("card_version")
    if type(rating) is not int or not 0 <= rating <= 3 or type(version) is not int or version < 1:
        raise DomainError("复习证据字段不合法")
    return {"title": text(payload.get("title", ""), "复习记录名称", 1100, True),
            "card_id": text(payload.get("card_id", ""), "复习卡 ID", 100, True),
            "rating": rating, "card_version": version,
            "request_id": text(payload.get("request_id", ""), "复习操作 ID", 100, True),
            "reviewed_at": timestamp(payload.get("reviewed_at", ""), "复习发生时间"),
            "previous_due_at": timestamp(payload.get("previous_due_at", ""), "原复习时间"),
            "next_due_at": timestamp(payload.get("next_due_at", ""), "下次复习时间")}


VALIDATORS = {"learning_card": validate_card, "learning_review": validate_review}


def validate_references(records: list[dict]) -> None:
    """来源和审计允许引用归档记录，但绝不指向私密或错误类型记录。"""
    indexed = {row["id"]: row for row in records}
    for row in records:
        if row["kind"] == "learning_card" and row["data"]["source"] != "manual":
            parent = indexed.get(row["data"]["source_id"])
            expected = "interview_report" if row["data"]["source"] == "interview" else "job_lead"
            if parent is None or parent["kind"] != expected:
                raise DomainError("复习卡来源记录缺失或类型不匹配")
        if row["kind"] == "learning_review":
            parent = indexed.get(row["data"]["card_id"])
            if parent is None or parent["kind"] != "learning_card":
                raise DomainError("复习证据缺少对应卡片")
