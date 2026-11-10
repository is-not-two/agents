"""确定性规则评分：纯函数，不调用模型、不读取配置或数据库。

所有阈值、词表与话术由调用方从 config/interview.yaml 注入；
同输入必得同输出，便于离线复现与量化对比。
"""
from __future__ import annotations

import re

from rag_tech_retriever.domains.life_planning import DomainError

TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.]{1,}")


def extract_terms(jd_text: str, limit: int = 40) -> list[str]:
    """从 JD 原文提取 ASCII 技术词，排序去重后截断，保证结果稳定。"""
    words = {match.group(0) for match in TERM_RE.finditer(jd_text or "")}
    return sorted(words, key=str.lower)[:limit]


def score_answers(turns: list[dict], jd_text: str, rubric: dict) -> dict:
    """按四个维度逐题打分并汇总；空回合直接拒绝。"""
    if not isinstance(turns, list) or not turns:
        raise DomainError("没有可评分的问答回合")
    if not isinstance(rubric, dict):
        raise DomainError("评分口径配置错误")
    max_score = int(rubric.get("max_score", 5))
    tiers = [int(t) for t in rubric.get("length_tiers", [30, 100, 200])]
    evidence = [str(m) for m in rubric.get("evidence_markers", [])]
    structure = [str(m) for m in rubric.get("structure_markers", [])]
    tips = rubric.get("tips", {}) if isinstance(rubric.get("tips"), dict) else {}
    names = [str(n) for n in rubric.get(
        "dimensions", ["具体性", "证据", "结构", "岗位关联"])]
    terms = extract_terms(jd_text, int(rubric.get("term_limit", 40)))

    per_turn = []
    for index, turn in enumerate(turns):
        answer = str(turn.get("answer", "")).strip() if isinstance(turn, dict) else ""
        length = len(answer)
        values = {
            "具体性": min(max_score, (1 if length else 0)
                       + sum(length >= tier for tier in tiers)),
            "证据": min(max_score, sum(1 for marker in evidence if marker in answer)),
            "结构": min(max_score, sum(1 for marker in structure if marker in answer)),
            "岗位关联": min(max_score, sum(1 for term in terms
                                      if term.lower() in answer.lower())),
        }
        per_turn.append({"index": index, "dimensions": values})

    dimensions = {
        name: round(sum(row["dimensions"].get(name, 0) for row in per_turn)
                    / len(per_turn), 1)
        for name in names
    }
    score = round(sum(dimensions.values()) / len(dimensions), 1) if dimensions else 0.0
    threshold = float(rubric.get("weak_threshold", 2))
    weak = [name for name in names if dimensions.get(name, 0) < threshold]
    feedback = "；".join(
        f"{name}偏弱：{tips.get(name, '补充相应细节')!s}" for name in weak
    ) or "各维度均有覆盖，继续保持具体证据。"
    return {
        "source": "rules",
        "score": score,
        "dimensions": dimensions,
        "per_turn": per_turn,
        "weak_points": weak,
        "feedback": feedback,
        "notes": str(rubric.get("notes", "规则评分，确定性口径；不是模型判断。")),
    }
