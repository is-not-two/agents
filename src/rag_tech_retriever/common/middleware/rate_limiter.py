"""接口限流中间件：按客户端滑动窗口计数，超限返回 429。

作用域：仅 /api/ 路径；键为客户端地址。limit<=0 表示关闭。
默认阈值从 web.yaml 的 web.rate_limit_per_minute 读取（缺省 120/分钟）。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from rag_tech_retriever.common.middleware.logger import get_logger, log_event
from rag_tech_retriever.common.middleware.tracer import current_request_id

limit_log = get_logger("ratelimit")


class SlidingWindowLimiter:
    """每键滑动窗口计数器：allow() 返回 (是否放行, 建议等待秒数)。"""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        if limit <= 0:
            raise ValueError("limit 必须 > 0；关闭限流请不入栈中间件")
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and moment - bucket[0] > self._window:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = max(1, int(self._window - (moment - bucket[0])) + 1)
                return False, retry_after
            bucket.append(moment)
            return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """对 /api/ 请求按客户端限流；超限返回 429 与 Retry-After。"""

    def __init__(self, app, limit: int, window_seconds: float = 60.0) -> None:
        super().__init__(app)
        self._off = limit <= 0
        self._limiter = None if self._off else SlidingWindowLimiter(limit, window_seconds)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self._off or not request.url.path.startswith("/api/"):
            return await call_next(request)
        assert self._limiter is not None
        key = request.client.host if request.client else "unknown"
        ok, retry_after = self._limiter.allow(key)
        if not ok:
            log_event(
                limit_log,
                "rate_limited",
                request_id=current_request_id(),
                client=key,
                path=request.url.path,
            )
            return JSONResponse(
                {
                    "detail": "请求过于频繁，请稍后再试",
                    "code": "RATE_LIMITED",
                    "request_id": current_request_id(),
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
