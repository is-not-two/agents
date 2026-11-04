"""提示词优化解析：JSON、代码块与纯文本都能安全落地。"""

from __future__ import annotations

import pytest

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
