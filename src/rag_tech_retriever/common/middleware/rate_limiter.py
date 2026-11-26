"""接口限流中间件：按客户端滑动窗口计数，超限返回 429。

作用域：仅 /api/ 路径；键为客户端地址。limit<=0 表示关闭。
默认阈值从 web.yaml 的 web.rate_limit_per_minute 读取（缺省 120/分钟）。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from math import isfinite

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from rag_tech_retriever.common.middleware.logger import get_logger, log_event
from rag_tech_retriever.common.middleware.tracer import current_request_id

limit_log = get_logger("ratelimit")
DEFAULT_MAX_CLIENTS = 4096
DEFAULT_MAX_EVENTS = 131072


class SlidingWindowLimiter:
    """每键滑动窗口计数器：allow() 返回 (是否放行, 建议等待秒数)。"""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        *,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit 必须 > 0；关闭限流请不入栈中间件")
        if not isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("rate limit window must be finite and positive")
        if not 1 <= max_clients <= 65536 or not 1 <= max_events <= 1048576:
            raise ValueError("rate limit state capacity outside safe bounds")
        self._limit = limit
        self._window = window_seconds
        self._max_clients = max_clients
        self._max_events = max_events
        self._hits: dict[str, deque[float]] = {}
        self._events: deque[tuple[float, str]] = deque()
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        moment = time.monotonic() if now is None else now
        with self._lock:
            # Expire all clients, including those who never visit again. Each
            # accepted event is enqueued/dequeued once; no full-dictionary sweep.
            while self._events and moment - self._events[0][0] > self._window:
                _, expired_key = self._events.popleft()
                expired_bucket = self._hits[expired_key]
                expired_bucket.popleft()
                if not expired_bucket:
                    del self._hits[expired_key]
            bucket = self._hits.get(key)
            if bucket is not None and len(bucket) >= self._limit:
                retry_after = max(1, int(self._window - (moment - bucket[0])) + 1)
                return False, retry_after
            if len(self._events) >= self._max_events or (
                bucket is None and len(self._hits) >= self._max_clients
            ):
                # Do not evict active clients to make room: doing so would reset
                # their quota. Rejected identities/events allocate no new state.
                retry_after = max(1, int(self._window - (moment - self._events[0][0])) + 1)
                return False, retry_after
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            bucket.append(moment)
            self._events.append((moment, key))
            return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """对 /api/ 请求按客户端限流；超限返回 429 与 Retry-After。"""

    def __init__(
        self,
        app,
        limit: int,
        window_seconds: float = 60.0,
        *,
        read_member: Callable[[str], str | None] | None = None,
        read_lookup_limit: int = 0,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        super().__init__(app)
        self._read_member = read_member
        self._lookup = SlidingWindowLimiter(read_lookup_limit, window_seconds, max_clients=max_clients, max_events=max_events) if read_lookup_limit > 0 and read_member else None
        self._off = limit <= 0
        self._limiter = (
            None
            if self._off
            else SlidingWindowLimiter(
                limit,
                window_seconds,
                max_clients=max_clients,
                max_events=max_events,
            )
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self._off or not request.url.path.startswith("/api/"):
            return await call_next(request)
        assert self._limiter is not None
        key = request.client.host if request.client else "unknown"
        quota_key = key
        ok, retry_after = True, 0
        if self._lookup and self._read_member and request.method == "GET" and request.url.path in {"/api/community/search", "/api/community/topics"}:
            token = request.cookies.get("__Secure-community_session", "")
            if len(token) == 43:
                ok, retry_after = self._lookup.allow(key)
                if ok:
                    member = await run_in_threadpool(self._read_member, token)
                    if member:
                        quota_key = "member:" + member
        if ok:
            ok, retry_after = self._limiter.allow(quota_key)
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
