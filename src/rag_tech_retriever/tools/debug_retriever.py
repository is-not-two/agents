"""检索调试工具（命中 chunk 列表、相似度分数、状态标记）。

以工厂形式绑定 SearchService 与 TTL 缓存：同一查询 30 秒内直接复用结果，
并在返回中标注 cached 与实际引擎（engine/notes 来自 SearchService，降级不冒充）。
"""

from __future__ import annotations

from rag_tech_retriever.common.middleware.cache import TTLCache

_VALID_SCOPES = {"all", "personal", "docs", "planning"}
_VALID_MODES = {"text", "vector"}
_MAX_QUERY = 500


def create_debug_retriever(search, cache: TTLCache | None = None):
    """返回绑定了检索服务与缓存的 debug_retriever(query, scope, mode) 函数。"""
    _cache = cache if cache is not None else TTLCache(maxsize=64, ttl_seconds=30)

    def debug_retriever(query: str, scope: str = "docs", mode: str = "text", namespace: str | None = None) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 必须是非空字符串")
        if len(query) > _MAX_QUERY:
            raise ValueError(f"query 过长（上限 {_MAX_QUERY} 字符）")
        if scope not in _VALID_SCOPES:
            raise ValueError(f"scope 必须是 {sorted(_VALID_SCOPES)} 之一")
        if mode not in _VALID_MODES:
            raise ValueError(f"mode 必须是 {sorted(_VALID_MODES)} 之一")
        cleaned = " ".join(query.split())
        selected = search.catalog.select(namespace) if hasattr(search, "catalog") else namespace
        key = f"{scope}|{mode}|{selected}|{cleaned}"
        cached = _cache.get(key)
        if cached is not None:
            return {**cached, "cached": True}
        result = search.query(cleaned, scope, mode, False) if namespace is None else search.query(cleaned, scope, mode, False, namespace)
        payload = {
            "query": cleaned,
            "scope": scope,
            "mode": mode,
            "engine": result["engine"],
            "hits": result["hits"],
            "notes": result["notes"],
            "cached": False,
            "namespace": selected,
        }
        _cache.put(key, payload)
        return payload

    return debug_retriever
