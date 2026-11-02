"""tools 三件套测试：stacktrace 解析（纯文本）、协议号查询（真实 PG 只读）、检索调试（假检索服务）。"""

from __future__ import annotations

import pytest

from rag_tech_retriever.tools.debug_retriever import create_debug_retriever
from rag_tech_retriever.tools.protocol_query import protocol_query
from rag_tech_retriever.tools.stacktrace_parser import parse_stacktrace

PY_TRACE = """Traceback (most recent call last):
  File "app.py", line 10, in handler
    return service.load(key)
  File "service.py", line 42, in load
    return mapping[key]
KeyError: 'user-profile'
"""

JS_TRACE = """TypeError: Cannot read properties of undefined (reading 'name')
    at renderUser (views.js:87:15)
    at render (views.js:30:5)
"""


class FakeSearch:
    def __init__(self):
        self.calls = []

    def query(self, query, scope, mode, generate):
        self.calls.append((query, scope, mode, generate))
        return {"query": query, "engine": "本地全文检索", "hits": [{"title": query}], "notes": []}


def test_stacktrace_python_full_shape():
    result = parse_stacktrace(PY_TRACE)
    assert result["language"] == "python"
    assert result["error_type"] == "KeyError"
    assert result["message"] == "'user-profile'"
    assert result["frame_count"] == 2
    assert result["frames"][-1] == {"file": "service.py", "line": 42, "in": "load"}
    assert any("键" in cause for cause in result["possible_causes"])
    assert any("service.py:42" in tip for tip in result["suggestions"])


def test_stacktrace_javascript_and_unknown():
    js = parse_stacktrace(JS_TRACE)
    assert js["language"] == "javascript"
    assert js["error_type"] == "TypeError"
    assert js["frames"][0]["file"] == "views.js" and js["frames"][0]["line"] == 87
    unknown = parse_stacktrace("something odd happened\nwithout any stack")
    assert unknown["language"] == "unknown"
    assert unknown["error_type"] == ""
    assert unknown["frame_count"] == 0


def test_stacktrace_rejects_bad_input():
    with pytest.raises(ValueError):
        parse_stacktrace("   ")
    with pytest.raises(ValueError):
        parse_stacktrace("x" * 20001)


def test_protocol_query_real_corpus_hit():
    """从真实语料自适应取样验证：取一个 h2 片段反查必命中（只读 SELECT）。"""
    from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

    client = PgVectorClient()
    try:
        client.connect()
        sample = client.fetch_all(
            "SELECT heading_path FROM rag_chunks WHERE namespace='tech_doc' "
            "AND heading_path <> '' LIMIT 1"
        )
    finally:
        client.close()
    assert sample, "tech_doc 语料为空，无法自适应测试"
    heading = sample[0]["heading_path"]
    fragment = heading.strip()[:6] or heading.strip()[:3]
    result = protocol_query(fragment, limit=3)
    assert result["count"] >= 1
    first = result["matches"][0]
    assert {"chunk_id", "source_file", "heading_path", "excerpt"} <= set(first)


def test_protocol_query_validates_input():
    for bad in ("", "   ", "%", "_", "x" * 65):
        with pytest.raises(ValueError):
            protocol_query(bad)
    from rag_tech_retriever.rag.vector_store.schema import SchemaError

    with pytest.raises(SchemaError):
        protocol_query("ok", table_name="rag_chunks; DROP TABLE x")


def test_debug_retriever_caches_and_validates():
    search = FakeSearch()
    retriever = create_debug_retriever(search)
    first = retriever("  检索 调试 ", "docs", "text")
    assert first["cached"] is False
    assert first["query"] == "检索 调试"
    second = retriever("检索 调试", "docs", "text")  # 归一化后同键 → 命中缓存
    assert second["cached"] is True
    assert len(search.calls) == 1
    assert search.calls[0] == ("检索 调试", "docs", "text", False)
    for bad_args in (("",), ("x", "bad"), ("x", "docs", "bad")):
        with pytest.raises(ValueError):
            retriever(*bad_args)
