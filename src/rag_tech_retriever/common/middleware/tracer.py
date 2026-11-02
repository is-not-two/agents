"""调用链路追踪中间件：请求 ID 生成/透传与访问日志。

约定：请求未携带 X-Request-ID 时生成短 ID；响应原样返回该头。
下游代码通过 current_request_id() 取值（含日志关联、限流记录）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from rag_tech_retriever.common.middleware.logger import get_logger, log_event

_request_id: ContextVar[str] = ContextVar("request_id", default="")
access_log = get_logger("access")


def current_request_id() -> str:
    """当前请求的追踪 ID；无请求上下文时为空串。"""
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class TracerMiddleware(BaseHTTPMiddleware):
    """注入请求 ID、输出一条结构化访问日志（方法/路径/状态/耗时）。"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or new_request_id()
        # 挂到 request.state（scope["state"] 全链路共享）：异常兜底处理在中间件外层执行时，
        # 上下文变量已重置，仍能取到同一 request_id 与访问日志关联。
        request.state.request_id = rid
        token = _request_id.set(rid)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            log_event(
                access_log,
                "http_request",
                request_id=rid,
                method=request.method,
                path=request.url.path,
                status=status,
                elapsed_ms=elapsed_ms,
            )
            _request_id.reset(token)
