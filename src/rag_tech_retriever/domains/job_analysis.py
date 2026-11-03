"""证据化 JD 规则；提取原文不是能力认定或录用预测。"""

from __future__ import annotations

import re

from rag_tech_retriever.domains.life_planning import DomainError, text

FACT_CATEGORIES = {"education", "experience", "availability", "language", "other"}
HARD_PATTERNS = {
    # “学历及经验”这类小标题不是要求本身，不能只凭“学历”二字生成硬条件。
    "education": r"学历要求|本科|硕士|博士|大专|学士|bachelor|master|phd",
    # “至少2年Python开发经验”中“年”与“经验”之间有其他词，需向前看确认语义。
    "experience": r"(?<!\d)\d{1,2}\+?\s*年(?:以上|及以上|左右)?(?=[^\n。；]{0,30}(?:经验|工作|开发))|years?|工作经验|实习经验|工作年限",
    "availability": r"到岗|每周|实习.{0,6}(?:月|天)|全职|出勤|onsite|on-site",
    "language": r"英语|四六级|CET[- ]?[46]|TOEFL|IELTS|English",
}


def validate_profile(payload: dict) -> dict:
    """仅收集自填证据，不读简历原文件，不接收模型密钥等未知字段。"""
    if not isinstance(payload, dict) or set(payload) - {"title", "skills", "facts"}:
        raise DomainError("求职资料字段不支持；请勿填入密钥或账号密码")
    skills, facts = payload.get("skills", []), payload.get("facts", [])
    if (
        not isinstance(skills, list)
        or len(skills) > 50
        or not isinstance(facts, list)
        or len(facts) > 20
    ):
        raise DomainError("技能最多 50 条，事实最多 20 条")
    clean, seen = [], set()
    for skill in skills:
        if not isinstance(skill, dict) or set(skill) - {"name", "evidence", "reference"}:
            raise DomainError("技能证据字段不支持")
        name = text(skill.get("name", ""), "技能名称", 80, True)
        if name.casefold() in seen:
            raise DomainError("技能名称不能重复")
        seen.add(name.casefold())
        clean.append(
            {
                "name": name,
                "evidence": text(skill.get("evidence", ""), "真实证据", 1000),
                "reference": text(skill.get("reference", ""), "证据来源", 500),
            }
        )
    normalized = []
    for fact in facts:
        if (
            not isinstance(fact, dict)
            or set(fact) - {"category", "value", "evidence"}
            or not isinstance(fact.get("category"), str)
            or fact["category"] not in FACT_CATEGORIES
        ):
            raise DomainError("硬条件事实类型不支持")
        normalized.append(
            {
                "category": fact["category"],
                "value": text(fact.get("value", ""), "个人事实", 1000, True),
                "evidence": text(fact.get("evidence", ""), "事实依据", 1000),
            }
        )
    return {
        "title": text(payload.get("title", "我的求职证据"), "资料名称", 160, True),
        "skills": clean,
        "facts": normalized,
    }


def _priority(quote: str) -> str:
    if re.search(r"不要求|不需要|无需|not required|no need", quote, re.IGNORECASE):
        return "not_required"
    if re.search(r"优先|加分|preferred|a plus", quote, re.IGNORECASE):
        return "preferred"
    if re.search(r"必须|要求|熟练|掌握|需具备|熟悉|精通|required|must", quote, re.IGNORECASE):
        return "required"
    return "mentioned"


def _evidence(name: str, profile: dict, taxonomy: list[dict]) -> tuple[str, list]:
    aliases = {name.casefold()}
    for item in taxonomy:
        if name.casefold() in {item["name"].casefold(), *[a.casefold() for a in item["aliases"]]}:
            aliases |= {item["name"].casefold(), *[a.casefold() for a in item["aliases"]]}
    matches = [s for s in profile["skills"] if s["name"].casefold() in aliases]
    supplied = [s for s in matches if s["evidence"] or s["reference"]]
    return (
        "evidence_supplied" if supplied else "declared_only" if matches else "not_in_profile"
    ), matches


def cite(jd: str, quote: str) -> dict:
    """必须是岗位原文中的精确非空片段，附原始字符串偏移。"""
    quote = text(quote, "JD 引用", 2000, True)
    start = jd.find(quote)
    if start < 0:
        raise DomainError("分析引用不是 JD 原文，已拒绝此结果")
    return {"quote": quote, "start": start, "end": start + len(quote)}


def rules_analysis(jd: str, profile: dict, taxonomy: list[dict]) -> dict:
    """保守提取：缺证据不等于不会，明确不要求的条目不变成学习缺口。"""
    text(jd, "岗位原文", 50000, True)  # Validate without shifting original citation offsets.
    profile = validate_profile(profile)
    requirements, hard, used = [], [], set()
    sentences = [
        match.group().strip()
        for match in re.finditer(r"[^\n。；;，,]+[。；;，,]?", jd)
        if match.group().strip()
    ]
    for sentence in sentences:
        quote = sentence[:2000]
        for category, pattern in HARD_PATTERNS.items():
            matched = re.search(pattern, sentence, re.IGNORECASE)
            if matched:
                excerpt = sentence[max(0, matched.start() - 500) :][:2000]
                hard.append(
                    {
                        "category": category,
                        **cite(jd, excerpt),
                        "priority": _priority(excerpt),
                        "profile_facts": [f for f in profile["facts"] if f["category"] == category],
                        "assessment": "needs_human_check",
                    }
                )
        for item in taxonomy:
            if item["name"] in used:
                continue
            matches = [
                re.search(
                    r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])",
                    sentence,
                    re.IGNORECASE,
                )
                for alias in item["aliases"]
            ]
            matched = next(
                (
                    match
                    for match in matches
                    # “ReAct”是推理框架，不是前端框架 React；大小写精确区分。
                    if match is not None
                    and not (item["name"] == "React" and match.group(0) == "ReAct")
                ),
                None,
            )
            if matched:
                quote = sentence[max(0, matched.start() - 500) :][:2000]
                assessment, evidence = _evidence(item["name"], profile, taxonomy)
                requirements.append(
                    {
                        "name": item["name"],
                        **cite(jd, quote),
                        "priority": _priority(quote),
                        "assessment": assessment,
                        "evidence": evidence,
                    }
                )
                used.add(item["name"])
    return {
        "requirements": requirements,
        "hard_conditions": hard,
        "notes": [
            "这是原文提取和自填证据对照，不是资格认定。资料未提供证据不代表你不会；硬条件须逐条人工核对。",
            "规则词表有覆盖边界，未提取的要求请结合完整 JD 阅读。",
        ],
        "quality_verified": False,
        "mode": "rules",
    }


def model_analysis(jd: str, profile: dict, taxonomy: list[dict], raw: dict) -> dict:
    """模型只能补充有原文依据的要求，不能替用户创造经历或削弱规则条件。"""
    if not isinstance(raw, dict) or set(raw) != {"requirements", "hard_conditions"}:
        raise DomainError("模型分析结构错误")
    result = rules_analysis(jd, profile, taxonomy)
    if (
        not isinstance(raw["requirements"], list)
        or len(raw["requirements"]) > 50
        or not isinstance(raw["hard_conditions"], list)
        or len(raw["hard_conditions"]) > 30
    ):
        raise DomainError("模型分析条目数量不合法")
    names = {item["name"].casefold() for item in result["requirements"]}
    for requirement in raw["requirements"]:
        if not isinstance(requirement, dict) or set(requirement) != {"name", "quote"}:
            raise DomainError("模型不能提供资格结论或伪造证据字段")
        name = text(requirement["name"], "要求名称", 80, True)
        citation = cite(jd, requirement["quote"])
        if name.casefold() not in citation["quote"].casefold():
            raise DomainError("模型要求名称与所引原文不一致")
        if name.casefold() in names:
            continue
        assessment, evidence = _evidence(name, profile, taxonomy)
        result["requirements"].append(
            {
                "name": name,
                **citation,
                "priority": _priority(citation["quote"]),
                "assessment": assessment,
                "evidence": evidence,
            }
        )
        names.add(name.casefold())
    for item in raw["hard_conditions"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"category", "quote"}
            or not isinstance(item["category"], str)
            or item["category"] not in FACT_CATEGORIES
        ):
            raise DomainError("模型硬条件结构错误")
        citation = cite(jd, item["quote"])
        if any(
            old["category"] == item["category"] and old["quote"] == citation["quote"]
            for old in result["hard_conditions"]
        ):
            continue
        result["hard_conditions"].append(
            {
                "category": item["category"],
                **citation,
                "priority": _priority(citation["quote"]),
                "profile_facts": [f for f in profile["facts"] if f["category"] == item["category"]],
                "assessment": "needs_human_check",
            }
        )
    result["mode"] = "model"
    result["notes"].append(
        "模型只补充有引用的条目；证据仍由原始自填资料投影，真实效果尚须人工核对。"
    )
    return result
