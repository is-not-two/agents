"""中间件五件套测试：单元（缓存/限流器）+ 集成（请求 ID、限流 429、访问日志）。"""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.middleware.cache import TTLCache
from rag_tech_retriever.common.middleware.exception import AppError, ErrorCode, RateLimitedError
from rag_tech_retriever.common.middleware.logger import JsonFormatter, get_logger
from rag_tech_retriever.common.middleware.rate_limiter import (
    RateLimitMiddleware,
    SlidingWindowLimiter,
)
from rag_tech_retriever.common.middleware.tracer import new_request_id


def test_cache_ttl_expiry_and_lru_eviction():
    # 余量放宽到 200ms/400ms：10ms 级余量在全量回归的高负载下会偶发抖动（2026-10-25 实测两次）
    cache = TTLCache(maxsize=2, ttl_seconds=0.2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # a 提升为最近使用
    cache.put("c", 3)  # 淘汰 b
    assert cache.get("b") is None
    assert cache.get("c") == 3
    import time as _time

    _time.sleep(0.4)
    assert cache.get("c") is None  # 过期


def test_cache_cached_wrapper_counts_hits():
    cache = TTLCache(maxsize=8, ttl_seconds=60)
    calls = []

    def double(x):
        calls.append(x)
        return x * 2

    fast = cache.cached(double, key_fn=lambda x: f"k{x}")
    assert fast(2) == 4 and fast(2) == 4 and fast(3) == 6
    assert calls == [2, 3]  # 第二次 fast(2) 走缓存，不再调用原函数
    assert cache.hits == 1 and cache.misses == 2


def test_limiter_sliding_window():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10)
    ok1, _ = limiter.allow("ip", now=0.0)
    ok2, _ = limiter.allow("ip", now=1.0)
    ok3, retry = limiter.allow("ip", now=2.0)
    assert (ok1, ok2, ok3) == (True, True, False)
    assert retry >= 1
    # 窗口滑过最旧记录后恢复
    ok4, _ = limiter.allow("ip", now=11.0)
    assert ok4 is True


def test_error_codes_stable_and_payload_shape():
    err = RateLimitedError("请求过于频繁，请稍后再试")
    assert err.code == ErrorCode.RATE_LIMITED
    assert err.http_status == 429
    payload = err.payload()
    assert payload["code"] == "RATE_LIMITED"
    assert "detail" in payload
    assert issubclass(AppError, Exception)


def test_json_formatter_single_line_with_fields():
    record = logging.LogRecord(
        "shilie.test", logging.INFO, __file__, 1, "hello", None, None
    )
    record.fields = {"request_id": "abc", "elapsed_ms": 1.5}
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["msg"] == "hello"
    assert payload["request_id"] == "abc"
    assert "\n" not in line


def _app():
    return create_app(store=_NoopStore())


class _NoopStore:
    """无数据库替身：所选测试端点（/、/api/session）不触达存储。"""

    def ensure_schema(self):
        return None


def test_request_id_header_echoed_and_generated():
    with TestClient(_app()) as client:
        first = client.get("/")
        assert first.status_code == 200
        assert len(first.headers.get("X-Request-ID", "")) == 12
        second = client.get("/", headers={"X-Request-ID": "custom-id-1"})
        assert second.headers["X-Request-ID"] == "custom-id-1"


def test_rate_limit_429_shape_and_retry_after():
    limited = RateLimitMiddleware(_app(), limit=1, window_seconds=60)
    client = TestClient(limited)
    first = client.get("/api/session")
    assert first.status_code == 200
    second = client.get("/api/session")
    assert second.status_code == 429
    assert second.headers.get("Retry-After")
    body = second.json()
    assert body["code"] == "RATE_LIMITED"
    assert "detail" in body
    # 页面与静态路径不受限流作用域影响
    assert client.get("/").status_code == 200


def test_rate_limit_env_override_disables(monkeypatch):
    """WEB_RATE_LIMIT_PER_MINUTE=0 应关闭限流（回归场景依赖此开关）。"""

    monkeypatch.setenv("WEB_RATE_LIMIT_PER_MINUTE", "0")
    # env() 优先走 os.environ，无需重建 ConfigLoader 单例
    app = create_app(store=_NoopStore())
    client = TestClient(app)
    for _ in range(130):  # 远超默认 120，未关闭则必然 429
        code = client.get("/api/session").status_code
        assert code != 429, "限流未按环境变量关闭"
    monkeypatch.delenv("WEB_RATE_LIMIT_PER_MINUTE")


def test_logger_name_and_request_id_format():
    logger = get_logger("unit")
    assert logger.name == "shilie.unit"
    rid = new_request_id()
    assert len(rid) == 12 and rid.isalnum()
