"""提示词优化解析：JSON、代码块与纯文本都能安全落地。"""

from __future__ import annotations

import pytest

from rag_tech_retriever.platform import prompt_optimizer as module
from rag_tech_retriever.platform.prompt_optimizer import OptimizeError, extract_optimized


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"optimized": "把目标、约束和期望输出写清楚"}', "把目标、约束和期望输出写清楚"),
        ('```json\n{"optimized": "先说明背景，再列步骤"}\n```', "先说明背景，再列步骤"),
        ('{"optimized_prompt": "保留原意并补充约束"}', "保留原意并补充约束"),
        ('{"prompt": "明确输入与输出格式"}', "明确输入与输出格式"),
        ("直接给出的改写文本", "直接给出的改写文本"),
    ],
)
def test_extract_accepts_common_model_shapes(raw, expected):
    assert extract_optimized(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "{}", '{"optimized": ""}', "[]"])
def test_extract_rejects_empty_or_invalid_results(raw):
    with pytest.raises(OptimizeError):
        extract_optimized(raw)


class _Connection:
    def __init__(self, config):
        self.config = config

    def load(self):
        return self.config


def test_optimize_prompt_posts_one_bounded_request(monkeypatch):
    """验证请求体、超时上限与用量解析；不发真实网络请求。"""
    seen = {}

    def fake_post(config, body, timeout, max_chars):
        seen.update(config=config, body=body, timeout=timeout, max_chars=max_chars)
        return {
            "choices": [{"message": {"content": '{"optimized": "更清晰的提示词"}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }

    monkeypatch.setattr(module, "post_chat", fake_post)
    result = module.optimize_prompt(
        _Connection({"api_key": "k", "base_url": "https://api.example.com", "model": "m"}),
        "system", "草稿", max_tokens=100, timeout=9,
    )
    assert result["optimized"] == "更清晰的提示词"
    assert result["usage"]["total_tokens"] == 12
    assert seen["body"]["temperature"] == 0.3
    assert seen["body"]["max_tokens"] == 100
    assert seen["body"]["messages"][0] == {"role": "system", "content": "system"}
    assert seen["body"]["messages"][1]["content"].startswith("<prompt_draft>")
    assert seen["timeout"] == 9


def test_optimize_prompt_requires_complete_connection():
    with pytest.raises(OptimizeError, match="尚未配置模型连接"):
        module.optimize_prompt(
            _Connection({"api_key": "", "base_url": "", "model": ""}), "system", "草稿"
        )

