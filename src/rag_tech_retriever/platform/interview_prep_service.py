"""模拟面试生成：规则 / 模型双模式，产物先过校验器再落库。

- 只读取已存在的岗位 JD 与简历解析文本，不抓取外部 URL。
- 提示词、题目模板、模型参数与备注文案全部来自 config/interview.yaml。
- 未配置模型连接时失败关闭；voice 模式冻结；规则题不代表真实面试官。
"""
from __future__ import annotations

import json
from pathlib import Path

from rag_tech_retriever.common.config_loader import PROJECT_ROOT, load_yaml_mapping
from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.interview_evaluation import score_answers
from rag_tech_retriever.domains.interview_prep import (
    FROZEN_MODES,
    validate_answers,
    validate_interview_prep,
)
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.record_store import RecordMissing

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "interview.yaml"


def load_interview_config(path: Path | None = None) -> dict:
    """读取独立配置；文件缺失时返回空字典，由服务层给出可读错误。"""
    target = path or DEFAULT_CONFIG_PATH
    if not target.is_file():
        return {}
    value = load_yaml_mapping(target).get("interview", {})
    return value if isinstance(value, dict) else {}


class InterviewPrepService:
    def __init__(self, store, resumes, connection=None, config=None) -> None:
        self.store = store
        self.resumes = resumes
        self.connection = connection
        self.config = load_interview_config() if config is None else config

    def _generation(self) -> dict:
        value = self.config.get("generation", {})
        return value if isinstance(value, dict) else {}

    def _notes(self, key: str, fallback: str) -> str:
        value = self.config.get("notes", {})
        return str(value.get(key, fallback)) if isinstance(value, dict) else fallback

    def _context(self, lead_id: str, resume_id: str) -> dict:
        try:
            lead = self.store.get(lead_id)
        except RecordMissing as exc:
            raise DomainError("岗位不存在") from exc
        if lead["kind"] != "job_lead":
            raise DomainError("岗位不存在")
        jd = str(lead["data"].get("jd_text", ""))
        if not jd.strip():
            raise DomainError("岗位没有 JD 原文，无法生成模拟面试")
        document = self.resumes.document(resume_id)
        resume_text = str(document.get("text", ""))
        if not resume_text.strip():
            raise DomainError("简历没有可读取的正文")
        return {
            "title": text(lead["data"].get("title", ""), "岗位", 160) or "模拟面试",
            "company": str(lead["data"].get("company", "")),
            "role": str(lead["data"].get("title", "")),
            "lead_id": lead_id,
            "resume_id": resume_id,
            "jd": jd,
            "resume_text": resume_text,
        }

    def _check_references(self, data: dict) -> None:
        """落库前确认岗位与简历引用真实存在，避免写入孤儿会话。"""
        for field, kind in (("lead_id", "job_lead"), ("resume_id", "resume_version")):
            reference = str(data.get(field, ""))
            if not reference:
                raise DomainError("模拟面试会话缺少岗位或简历关联")
            try:
                row = self.store.get(reference)
            except RecordMissing as exc:
                raise DomainError("模拟面试会话关联的记录不存在") from exc
            if row.get("kind") != kind or row.get("deleted"):
                raise DomainError("模拟面试会话关联的记录类型不正确或已删除")

    def rules_draft(self, ctx: dict, mode: str) -> dict:
        """确定性模板题：本地可验证，不调用模型。"""
        raw = self.config.get("rule_questions", [])
        questions = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    questions.append(item.format(company=ctx["company"], role=ctx["role"]))
        if not questions:
            raise DomainError("缺少规则题目配置")
        limit = int(self._generation().get("turns_max", 30))
        turns = [{"q": q, "answer": "", "suggestion": ""}
                 for q in questions[:limit]]
        return {
            "title": f"模拟面试 · {ctx['company']} · {ctx['role']}",
            "company": ctx["company"],
            "role": ctx["role"],
            "lead_id": ctx["lead_id"],
            "resume_id": ctx["resume_id"],
            "mode": mode,
            "turns": turns,
            "notes": self._notes("rules", "规则模板题，未调用模型。"),
            "audio": {},
        }

    def model_draft(self, ctx: dict, mode: str, post=None) -> dict:
        config = self.connection.load() if self.connection else {}
        if not (config.get("api_key") and config.get("base_url") and config.get("model")):
            raise ProviderError("尚未配置模型连接，未发起请求")
        gen = self._generation()
        requirement = self.config.get("modes", {})
        requirement = requirement.get(mode, "") if isinstance(requirement, dict) else ""
        prompt = str(self.config.get("system_prompt", "")).strip()
        if not prompt:
            raise DomainError("缺少模拟面试提示词配置")
        jd_limit = int(gen.get("max_jd_chars", 30000))
        resume_limit = int(gen.get("max_resume_chars", 30000))
        body = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": prompt + " " + str(requirement)},
                {"role": "user", "content": "【岗位 JD】\n" + ctx["jd"][:jd_limit]
                 + "\n\n【简历正文】\n" + ctx["resume_text"][:resume_limit]},
            ],
            "temperature": 0,
            "max_tokens": int(gen.get("max_tokens", 1800)),
        }
        reply = (post or post_chat)(
            config, body,
            timeout=int(gen.get("timeout_seconds", 25)),
            max_chars=int(gen.get("max_reply_chars", 120000)),
        )
        choices = reply.get("choices") or []
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise DomainError("模型未返回可解析的模拟面试结果")
        try:
            raw = json.loads(content.strip())
        except (ValueError, TypeError) as exc:
            raise DomainError("模型输出不是合法 JSON") from exc
        turns = raw.get("turns") if isinstance(raw, dict) else None
        low = int(gen.get("turns_min", 1))
        high = int(gen.get("turns_max", 30))
        if not isinstance(turns, list) or not low <= len(turns) <= high:
            raise DomainError("模型生成的问答回合数量不合法")
        return {
            "title": f"模拟面试 · {ctx['company']} · {ctx['role']}",
            "company": ctx["company"],
            "role": ctx["role"],
            "lead_id": ctx["lead_id"],
            "resume_id": ctx["resume_id"],
            "mode": mode,
            "turns": turns,
            "notes": self._notes("model", "模型生成，质量未验证。"),
            "audio": {},
        }

    def generate(self, lead_id: str, resume_id: str, mode: str = "practice",
                 use_model: bool = False, post=None) -> dict:
        if mode in FROZEN_MODES:
            raise DomainError("语音模拟已冻结，请使用练习 / 完整问答模式")
        if mode not in {"practice", "full"}:
            raise DomainError("生成只支持练习 / 完整问答模式")
        ctx = self._context(lead_id, resume_id)
        draft = (self.model_draft(ctx, mode, post) if use_model
                 else self.rules_draft(ctx, mode))
        if mode == "practice":
            for turn in draft["turns"]:
                turn["answer"] = ""
                turn["suggestion"] = ""
        return validate_interview_prep(draft)

    def save(self, draft: dict, record_id=None, version=None) -> dict:
        data = validate_interview_prep(draft)
        self._check_references(data)
        return self.store.save("interview_prep", data, record_id, version)

    def submit_answers(self, record_id, version, answers) -> dict:
        """显式提交逐题作答；只改指定题号的 answer，其余字段原样保留。"""
        try:
            row = self.store.get(record_id)
        except RecordMissing as exc:
            raise DomainError("模拟面试会话不存在") from exc
        if row.get("kind") != "interview_prep":
            raise DomainError("记录不是模拟面试会话")
        data = validate_interview_prep(row.get("data", {}))
        for item in validate_answers(data["turns"], answers):
            data["turns"][item["index"]]["answer"] = item["answer"]
        return self.store.save("interview_prep", data, record_id, version)

    def evaluate(self, record_id, version, source="rules") -> dict:
        """确定性规则评分；模型评分未启用时明确拒绝，不伪造 AI 结论。"""
        if source != "rules":
            raise DomainError("模型评分尚未启用，本批只提供确定性规则评分")
        try:
            row = self.store.get(record_id)
        except RecordMissing as exc:
            raise DomainError("模拟面试会话不存在") from exc
        if row.get("kind") != "interview_prep":
            raise DomainError("记录不是模拟面试会话")
        data = validate_interview_prep(row.get("data", {}))
        if not any(turn["answer"].strip() for turn in data["turns"]):
            raise DomainError("请先至少作答一题再评分")
        try:
            lead = self.store.get(data["lead_id"])
        except RecordMissing as exc:
            raise DomainError("关联岗位不存在") from exc
        result = score_answers(
            data["turns"], str(lead["data"].get("jd_text", "")),
            self.config.get("rubric", {}),
        )
        data["evaluation"] = result
        return self.store.save("interview_prep", data, record_id, version)
