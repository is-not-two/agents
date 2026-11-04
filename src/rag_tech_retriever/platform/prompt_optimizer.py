"""提示词优化：单次模型调用，只改写草稿，不持久化原文。"""

from __future__ import annotations

import json
import re

from rag_tech_retriever.common.provider import ProviderError, post_chat, usage_metadata
from rag_tech_retriever.platform.model_connection import ModelConnection, StorageError


class OptimizeError(RuntimeError):
    """可安全返回给客户端的优化失败。"""


def extract_optimized(content: object) -> str:
    """模型可能返回 JSON、带代码块的 JSON 或纯文本；三种都接受。"""
    text = str(content or "").strip()
    if not text:
        raise OptimizeError("模型没有返回优化结果，请稍后重试")
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(value, dict):
        for key in ("optimized", "optimized_prompt", "prompt"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise OptimizeError("模型返回的优化结果格式无效，请重试")


def optimize_prompt(
    connection: ModelConnection,
    system: str,
    draft: str,
    *,
    max_tokens: int = 800,
    timeout: int = 25,
    max_context_chars: int = 120000,
) -> dict:
    """调用一次模型改写提示词；连接未配置或失败时抛出安全错误。"""
    try:
        config = connection.load()
    except StorageError as exc:
        raise OptimizeError("无法读取模型连接，请检查服务器配置") from exc
    if not all(config.get(key) for key in ("api_key", "base_url", "model")):
        raise OptimizeError("尚未配置模型连接，无法优化提示词")
    body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"<prompt_draft>\n{draft}\n</prompt_draft>"},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
    }
    try:
        envelope = post_chat(config, body, timeout, max_context_chars)
        content = envelope["choices"][0]["message"]["content"]
    except (ProviderError, KeyError, IndexError, TypeError) as exc:
        raise OptimizeError("模型未返回可用的优化结果，本次未自动重试") from exc
    optimized = extract_optimized(content)
    return {"optimized": optimized, "model": config["model"],
            "usage": usage_metadata(envelope.get("usage"))}
