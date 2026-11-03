"""Web search provider normalization, caching and fail-closed config."""

import json

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.web_search import SearchError, WebSearch

DDG = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpython&amp;rut=x">Python 官方</a>
  <a class="result__snippet">Python 是一种编程语言。</a>
</div>
<div class="result">
  <a class="result__a" href="https://docs.python.org/3/">Python 文档</a>
  <div class="result__snippet">标准库与教程。</div>
</div>
<div class="result">
  <a class="result__a" href="javascript:alert(1)">危险链接</a>
</div>
"""


def make(provider="duckduckgo", value=None):
    config = {"enabled": True, "provider": provider, "max_results": 3}
    return WebSearch(config, lambda name, default="": value if name == "TAVILY_API_KEY" else default)


def test_duckduckgo_results_are_normalized_deduplicated_and_cached():
    search = make()
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return DDG.encode()

    search._request = request
    first = search.search("Python")
    assert first["provider"] == "duckduckgo" and first["cached"] is False
    assert [row["url"] for row in first["results"]] == [
        "https://example.com/python", "https://docs.python.org/3/"]
    assert "编程语言" in first["results"][0]["snippet"]
    second = search.search("Python")
    assert second["cached"] is True and len(calls) == 1
    assert "javascript:" not in json.dumps(first)


def test_tavily_results_and_key_requirement():
    search = make("tavily", "test-key")
    payload = {"results": [
        {"title": "A", "url": "https://example.com/a", "content": "摘要", "score": 0.9},
        {"title": "B", "url": "http://localhost/b", "content": "应被过滤", "score": 0.1},
    ]}
    search._request = lambda url, **kwargs: json.dumps(payload).encode()
    result = search.search("query", 2)
    assert [row["url"] for row in result["results"]] == ["https://example.com/a"]


def test_bing_results_are_normalized():
    search = make("bing")
    html = """<li class="b_algo"><h2><a href="https://example.com/a">标题 A</a></h2><p>摘要 A</p></li>
    <li class="b_algo"><h2><a href="javascript:void(0)">危险</a></h2></li>
    <li class="b_algo"><h2><a href="https://example.com/b">标题 B</a></h2><p>摘要 B</p></li>"""
    search._request = lambda url, **kwargs: html.encode()
    result = search.search("query", 2)
    assert [row["url"] for row in result["results"]] == ["https://example.com/a", "https://example.com/b"]
    assert result["results"][0]["snippet"] == "摘要 A"


def test_disabled_and_invalid_config_fail_closed():
    with pytest.raises(SearchError, match="未启用"):
        WebSearch({"enabled": False}, lambda *args: None).search("x")
    with pytest.raises(DomainError):
        WebSearch({"enabled": True, "provider": "google"}, lambda *args: None)
    with pytest.raises(DomainError):
        WebSearch({"enabled": True, "timeout_seconds": 1}, lambda *args: None)
    with pytest.raises(SearchError, match="密钥未配置"):
        make("tavily", "").search("x")
