"""模拟面试会话契约：面之前的练习与示范问答，与真实面试复盘分开存储。

设计边界
- 不写入 interview_report：那是面完复盘，混用会污染真实面试数据。
- turns[] 是各模式共用的数据结构；voice 已冻结，audio 只留一个受限字典，
  不放任意结构或二进制内容。
- 规则模式产生的题目是模板，不代表真实面试官的问题。
"""
from __future__ import annotations

import json
from copy import deepcopy

from rag_tech_retriever.domains.life_planning import DomainError, text

MODES = ("practice", "full", "voice")
#: 语音模拟继续冻结：契约保留数据结构，生成与评分均拒绝该模式。
FROZEN_MODES = ("voice",)


def validate_answers(turns: list[dict], answers: object) -> list[dict]:
    """校验逐题作答：题号合法、不重复、答案长度受控，返回按题号排序的规范化列表。"""
    if not isinstance(answers, list) or not answers:
        raise DomainError("请提交至少一条作答")
    if not isinstance(turns, list):
        raise DomainError("会话回合格式错误")
    normalized: list[dict] = []
    seen: set[int] = set()
    for item in answers:
        if not isinstance(item, dict):
            raise DomainError("作答格式错误")
        index = item.get("index")
        if (not isinstance(index, int) or isinstance(index, bool)
                or not 0 <= index < len(turns)):
            raise DomainError("作答题号超出会话范围")
        if index in seen:
            raise DomainError("同一题号重复提交")
        seen.add(index)
        normalized.append({
            "index": index,
            "answer": text(item.get("answer", ""), "回答", 8000),
        })
    return sorted(normalized, key=lambda row: row["index"])


def validate_interview_prep(payload: dict) -> dict:
    """校验并规范化一次模拟面试会话；拒绝越界模式与超长回合。"""
    if not isinstance(payload, dict):
        raise DomainError("模拟面试会话格式错误")
    mode = payload.get("mode", "practice")
    if mode not in MODES:
        raise DomainError("模拟面试模式只支持练习 / 完整问答 / 语音模拟")
    raw_turns = payload.get("turns", [])
    if not isinstance(raw_turns, list) or not 1 <= len(raw_turns) <= 30:
        raise DomainError("请保留 1–30 个问答回合")
    turns = []
    for item in raw_turns:
        if not isinstance(item, dict):
            raise DomainError("问答回合格式错误")
        turns.append({
            "q": text(item.get("q", ""), "面试问题", 2000, True),
            "answer": text(item.get("answer", ""), "回答", 8000),
            "suggestion": text(item.get("suggestion", ""), "优化建议", 4000),
        })
    audio = payload.get("audio", {})
    if not isinstance(audio, dict) or len(json.dumps(audio, ensure_ascii=False)) > 4000:
        raise DomainError("语音参数必须是受限对象")
    evaluation = payload.get("evaluation", {})
    if (not isinstance(evaluation, dict)
            or len(json.dumps(evaluation, ensure_ascii=False)) > 8000):
        raise DomainError("评分结果必须是受限对象")
    return {
        "title": text(payload.get("title", ""), "会话标题", 160, True),
        "company": text(payload.get("company", ""), "公司", 160),
        "role": text(payload.get("role", ""), "岗位", 160),
        "lead_id": text(payload.get("lead_id", ""), "岗位 ID", 100),
        "resume_id": text(payload.get("resume_id", ""), "简历 ID", 100),
        "mode": mode,
        "turns": turns,
        "notes": text(payload.get("notes", ""), "会话备注", 10000),
        "audio": deepcopy(audio),
        "evaluation": deepcopy(evaluation),
    }
