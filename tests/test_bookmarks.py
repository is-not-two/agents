"""网页收藏校验测试（纯函数，无数据库）。

规则：仅接受完整的 http/https 外链；拒绝空白字符、账号密码与其它协议；
分类留空回落「未分类」；标签沿用知识条的逗号/顿号拆分，最多 10 个。
"""

import pytest

from rag_tech_retriever.domains.bookmarks import DEFAULT_CATEGORY, validate_bookmark
from rag_tech_retriever.domains.life_planning import DomainError

BASE = {"title": "FastAPI 文档", "url": "https://fastapi.tiangolo.com/"}


def test_https_url_normalized_with_default_category():
    result = validate_bookmark(BASE)
    assert result["url"] == "https://fastapi.tiangolo.com/"
    assert result["category"] == DEFAULT_CATEGORY
    assert result["tags"] == []
    assert result["note"] == ""


def test_http_scheme_allowed_and_category_trimmed():
    result = validate_bookmark(
        {**BASE, "url": "http://example.com/a", "category": "  文档与教程  "}
    )
    assert result["url"] == "http://example.com/a"
    assert result["category"] == "文档与教程"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<h1>x</h1>",
        "mailto:a@example.com",
        "/relative/path",
        "example.com",
    ],
)
def test_non_http_links_rejected(url):
    with pytest.raises(DomainError):
        validate_bookmark({**BASE, "url": url})


def test_whitespace_in_url_rejected():
    with pytest.raises(DomainError):
        validate_bookmark({**BASE, "url": "https://example.com/a b"})


def test_credentials_in_url_rejected():
    with pytest.raises(DomainError):
        validate_bookmark({**BASE, "url": "https://user:pass@example.com/"})


def test_title_and_url_required():
    with pytest.raises(DomainError):
        validate_bookmark({"url": "https://example.com/"})
    with pytest.raises(DomainError):
        validate_bookmark({"title": "只有标题"})


def test_tags_split_and_limit_ten():
    result = validate_bookmark({**BASE, "tags": ["Python，RAG、后端", "RAG"]})
    assert result["tags"] == ["Python", "RAG", "后端"]
    with pytest.raises(DomainError):
        validate_bookmark({**BASE, "tags": [f"t{i}" for i in range(11)]})


def test_category_length_limit():
    with pytest.raises(DomainError):
        validate_bookmark({**BASE, "category": "c" * 25})
