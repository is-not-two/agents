"""LEARN-001 标签规范化测试（纯函数，无数据库）。

规范：英文逗号/中文逗号/顿号拆分；去两端空白；丢弃空项；重复项保留首次顺序；
最多 15 个、单个最多 40 字的既有约束继续生效。
"""

import pytest

from rag_tech_retriever.domains.knowledge import normalize_tags, validate_knowledge
from rag_tech_retriever.domains.life_planning import DomainError

BASE = {"title": "标题", "content": "正文"}


def test_english_comma_splits_two():
    assert normalize_tags(["Python,RAG"]) == ["Python", "RAG"]


def test_chinese_separators_split_three():
    assert normalize_tags(["Python，RAG、后端"]) == ["Python", "RAG", "后端"]


def test_whitespace_and_duplicates_normalized_in_order():
    assert normalize_tags([" Python ,RAG ", "RAG", " 后端 "]) == [
        "Python",
        "RAG",
        "后端",
    ]


def test_empty_or_separator_only_yields_empty_list():
    assert normalize_tags(["", " , ,、"]) == []
    assert validate_knowledge({**BASE, "tags": ["、"]})["tags"] == []


def test_sixteen_distinct_tags_rejected():
    tags = [f"t{i}" for i in range(16)]
    with pytest.raises(DomainError):
        validate_knowledge({**BASE, "tags": tags})
    # 15 个正好通过
    ok = validate_knowledge({**BASE, "tags": tags[:15]})
    assert len(ok["tags"]) == 15


def test_html_like_tag_stays_plain_text():
    result = validate_knowledge({**BASE, "tags": ["<b>x</b>"]})
    assert result["tags"] == ["<b>x</b>"]


def test_non_string_tag_rejected():
    with pytest.raises(DomainError):
        validate_knowledge({**BASE, "tags": [123]})


def test_oversize_single_tag_rejected_after_split():
    with pytest.raises(DomainError):
        validate_knowledge({**BASE, "tags": ["a" * 41]})
