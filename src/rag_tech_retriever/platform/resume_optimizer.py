"""AI 优化简历：模板驱动、生成草稿、人工确认后另存留痕。

边界
- 模板内容由用户提供，仓库不内置猜测模板；未配置时明确报缺，不放假功能。
- 未配置模型连接时不发起请求、不返回伪造改写。
- 草稿不自动覆盖简历本体；用户确认后另存为一条知识记录，保留版本历史。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from rag_tech_retriever.common.config_loader import PROJECT_ROOT
from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.knowledge import validate_knowledge
from rag_tech_retriever.domains.life_planning import DomainError, text

TEMPLATE_PATH = PROJECT_ROOT / "config" / "resume_templates.yaml"
CONFIRMATION = "确认另存优化草稿"


class ResumeOptimizer:
    def __init__(self, store, resumes, connection=None) -> None:
        self.store = store
        self.resumes = resumes
        self.connection = connection

    def templates(self) -> list[dict]:
        """只返回模板标识与名称，不把 system 提示词发给浏览器。"""
        raw = {}
        if TEMPLATE_PATH.is_file():
            try:
                raw = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise DomainError("简历模板配置无法读取") from exc
        items = raw.get("templates", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            raise DomainError("简历模板配置格式错误")
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = text(item.get("name", ""), "模板名称", 80, True)
            cleaned.append({"id": text(item.get("id", ""), "模板 ID", 64, True), "name": name})
        return cleaned

    def _template(self, template_id: str) -> dict:
        raw = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8")) if TEMPLATE_PATH.is_file() else {}
        items = raw.get("templates", []) if isinstance(raw, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("id") == template_id:
                system = text(item.get("system", ""), "模板指令", 10000, True)
                return {"id": template_id, "name": text(item.get("name", ""), "模板名称", 80, True),
                        "system": system}
        raise DomainError("尚未配置该优化模板")

    def draft(self, template_id: str, resume_id: str, lead_id: str, post=None) -> dict:
        template = self._template(template_id)
        config = self.connection.load() if self.connection else {}
        if not (config.get("api_key") and config.get("base_url") and config.get("model")):
            raise ProviderError("尚未配置模型连接，未发起请求")
        document = self.resumes.document(resume_id)
        lead = self.store.get(lead_id)
        if lead["kind"] != "job_lead" or not lead["data"].get("jd_text"):
            raise DomainError("岗位不存在或没有 JD 原文")
        body = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": template["system"]},
                {"role": "user", "content": "【岗位 JD】\n" + str(lead["data"]["jd_text"])[:20000]
                 + "\n\n【简历正文】\n" + str(document.get("text", ""))[:50000]},
            ],
            "temperature": 0,
            "max_tokens": 2000,
        }
        reply = (post or post_chat)(config, body, timeout=60, max_chars=120000)
        choices = reply.get("choices") or []
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise DomainError("模型未返回可用的优化草稿")
        return {
            "template": template["name"],
            "draft": content.strip()[:50000],
            "quality_verified": False,
            "note": "草稿未写库；确认后另存为独立知识记录，不会覆盖简历本体。",
        }

    def apply(self, title: str, draft: str, confirmation: str) -> dict:
        """人工确认后另存，保留版本历史；不改动 resume_version。"""
        if confirmation != CONFIRMATION:
            raise DomainError("请明确确认另存优化草稿")
        data = validate_knowledge({
            "title": text(title, "记录标题", 160, True),
            "content": text(draft, "优化草稿", 50000, True),
            "source": "AI 优化简历",
            "tags": ["简历优化"],
        })
        return self.store.save("knowledge", data)


def template_config_path() -> Path:
    return TEMPLATE_PATH
