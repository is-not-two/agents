"""预面试生成：规则 / 模型双模式，产物先过校验器再落库。

- 只读取已存在的岗位 JD 与简历解析文本，不抓取外部 URL。
- 未配置模型连接时失败关闭；规则模式是确定性模板题，明确标注未调用模型。
- voice 模式保留数据结构，本轮不实现音频生成与识别。
"""
from __future__ import annotations

import json

from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.interview_prep import validate_interview_prep
from rag_tech_retriever.domains.life_planning import DomainError, text

SYSTEM_PROMPT = (
    "你是面试官，为一场预面试生成问答。只依据给定的岗位 JD 与简历正文，"
    "禁止编造候选人的项目、数字或经历；不确定的地方写成建议而非结论。"
    '只返回 JSON：{"turns":[{"q":"问题","answer":"示范回答","suggestion":"优化建议"}]}。'
    "生成 5–8 个回合，覆盖经历、取舍、能力与风险；不要代码块或解释。"
)


class InterviewPrepService:
    def __init__(self, store, resumes, connection=None) -> None:
        self.store = store
        self.resumes = resumes
        self.connection = connection

    def _context(self, lead_id: str, resume_id: str) -> dict:
        lead = self.store.get(lead_id)
        if lead["kind"] != "job_lead":
            raise DomainError("岗位不存在")
        jd = str(lead["data"].get("jd_text", ""))
        if not jd.strip():
            raise DomainError("岗位没有 JD 原文，无法生成预面试")
        document = self.resumes.document(resume_id)
        resume_text = str(document.get("text", ""))
        if not resume_text.strip():
            raise DomainError("简历没有可读取的正文")
        return {
            "title": text(lead["data"].get("title", ""), "岗位", 160) or "预面试",
            "company": str(lead["data"].get("company", "")),
            "role": str(lead["data"].get("title", "")),
            "lead_id": lead_id,
            "resume_id": resume_id,
            "jd": jd,
            "resume_text": resume_text,
        }

    def rules_draft(self, ctx: dict, mode: str) -> dict:
        """确定性模板题：本地可验证，不调用模型。"""
        questions = [
            f"请结合简历，说明你与「{ctx['company']} / {ctx['role']}」最匹配的经历。",
            "描述一次你在项目里的关键取舍，以及结果是怎么验证的。",
            "JD 里要求的核心能力，你有哪些可以落到具体事情的证据？",
            "如果需求中途变化，你会如何调整方案、排期与沟通？",
            "你希望在未来半年补齐哪一块能力，为什么？",
        ]
        turns = [{"q": q, "answer": "", "suggestion": ""} for q in questions]
        return {
            "title": f"预面试 · {ctx['company']} · {ctx['role']}",
            "company": ctx["company"],
            "role": ctx["role"],
            "lead_id": ctx["lead_id"],
            "resume_id": ctx["resume_id"],
            "mode": mode,
            "turns": turns,
            "notes": "规则模板题，未调用模型；不代表真实面试官的问题。",
            "audio": {},
        }

    def model_draft(self, ctx: dict, mode: str, post=None) -> dict:
        config = self.connection.load() if self.connection else {}
        if not (config.get("api_key") and config.get("base_url") and config.get("model")):
            raise ProviderError("尚未配置模型连接，未发起请求")
        requirement = (
            "完整问答模式：每回合都给出示范回答与优化建议。"
            if mode == "full"
            else "练习模式：只给问题，answer 与 suggestion 留空字符串。"
        )
        body = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + " " + requirement},
                {"role": "user", "content": "【岗位 JD】\n" + ctx["jd"][:20000]
                 + "\n\n【简历正文】\n" + ctx["resume_text"][:50000]},
            ],
            "temperature": 0,
            "max_tokens": 2500,
        }
        reply = (post or post_chat)(config, body, timeout=60, max_chars=120000)
        choices = reply.get("choices") or []
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise DomainError("模型未返回可解析的预面试结果")
        try:
            raw = json.loads(content.strip())
        except (ValueError, TypeError) as exc:
            raise DomainError("模型输出不是合法 JSON") from exc
        turns = raw.get("turns") if isinstance(raw, dict) else None
        if not isinstance(turns, list) or not 1 <= len(turns) <= 30:
            raise DomainError("模型生成的问答回合数量不合法")
        return {
            "title": f"预面试 · {ctx['company']} · {ctx['role']}",
            "company": ctx["company"],
            "role": ctx["role"],
            "lead_id": ctx["lead_id"],
            "resume_id": ctx["resume_id"],
            "mode": mode,
            "turns": turns,
            "notes": "模型生成，质量未验证；示范回答与建议需人工核对。",
            "audio": {},
        }

    def generate(self, lead_id: str, resume_id: str, mode: str = "practice",
                 use_model: bool = False, post=None) -> dict:
        if mode not in {"practice", "full"}:
            raise DomainError("生成只支持练习 / 完整问答模式，语音模拟后续接入")
        ctx = self._context(lead_id, resume_id)
        draft = (self.model_draft(ctx, mode, post) if use_model
                 else self.rules_draft(ctx, mode))
        if mode == "practice":
            for turn in draft["turns"]:
                turn["answer"] = ""
                turn["suggestion"] = ""
        return validate_interview_prep(draft)

    def save(self, draft: dict) -> dict:
        return self.store.save("interview_prep", validate_interview_prep(draft))
